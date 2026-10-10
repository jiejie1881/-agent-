"""Small, opt-in Demo fixture. Never delete data or take over a mixed database."""
import argparse
import json
import os
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.domain.enums import UserRole, VehicleTypeCode
from app.domain.exceptions import ConflictError
from app.models.delivery_demand import DeliveryDemand
from app.models.dispatch_plan import DispatchPlan
from app.models.route import Route, RouteTerrainConfig
from app.models.store import Store, StoreRoute
from app.models.terrain import Terrain
from app.models.user import User
from app.models.vehicle import Vehicle, VehicleType
from app.schemas.auto_dispatch import AutoDispatchRequest
from app.schemas.delivery_demand import DeliveryDemandCreate
from app.schemas.driver import DeliveryStopFailRequest, DeliveryStopSignRequest
from app.schemas.driver_scheduling import DriverCreateInput, FixedAttendanceInput, ScheduleInput
from app.schemas.route import RouteCreate, RouteTerrainCreate
from app.schemas.store import StoreCreate
from app.schemas.terrain import TerrainCreate
from app.schemas.vehicle import VehicleCreate, VehicleTypeCreate
from app.schemas.vehicle_attendance import VehicleAttendanceCreate
from app.services.auth_service import AuthService
from app.services.auto_dispatch_service import AutoDispatchService
from app.services.delivery_demand_service import DeliveryDemandService
from app.services.dispatch_plan_service import DispatchPlanService
from app.services.driver_service import DriverService
from app.services.driver_scheduling_service import DriverSchedulingService
from app.services.route_service import RouteService, RouteTerrainService
from app.services.store_service import StoreService, StoreRouteService
from app.services.terrain_service import TerrainService
from app.services.vehicle_attendance_service import VehicleAttendanceService
from app.services.vehicle_service import (
    VehicleService, VehicleTypeService, VehicleTypeTerrainPermissionService,
)

DATABASES = {"logistics_dispatch_demo_compact", "logistics_dispatch_demo_verify"}
DRIVERS = ("张建军", "李志强", "王海波", "陈志远", "赵明远")
TYPE_CONFIG = (("FOUR_METER", "4.2米厢式货车", 630, 800),
               ("BIG_VAN", "大型面包车", 300, 420), ("SMALL_VAN", "小型面包车", 1, 300))
# Coordinates reuse the existing YueLu geographic Demo locations, not customer addresses.
STORES = (
    ("麓谷科技园店", "长沙市岳麓区麓谷科技园", "112.8916273", "28.2171916", 1),
    ("天顶社区店", "长沙市岳麓区天顶街道", "112.8837300", "28.2051221", 2),
    ("洋湖新城店", "长沙市岳麓区洋湖片区", "112.9199935", "28.1042711", 3),
    ("含浦综合店", "长沙市岳麓区含浦片区", "112.8512300", "28.1033004", 3),
    ("学士工业园店", "长沙市岳麓区学士街道", "112.8664769", "28.1244614", 3),
    ("梅溪湖中央店", "长沙市岳麓区梅溪湖片区", "112.8907111", "28.1917313", 2),
    ("望月湖社区店", "长沙市岳麓区望月湖街道", "112.9470476", "28.2050334", 2),
)
# (store index, period, quantity in kg)
DEMANDS = ((1, "MORNING", 700), (2, "MORNING", 350),
           (3, "MORNING", 80), (4, "MORNING", 70),
           (5, "MORNING", 90), (1, "AFTERNOON", 700),
           (2, "AFTERNOON", 350), (3, "AFTERNOON", 80))
AI_DEMANDS = ((5, "AFTERNOON", 90), (4, "AFTERNOON", 60),
              (6, "AFTERNOON", 40), (7, "AFTERNOON", 30))


def validate_target(url, local_demo, expected_database):
    parsed = make_url(url)
    if not local_demo or expected_database not in DATABASES or parsed.database != expected_database:
        raise ValueError("必须明确指定独立精简Demo库，禁止接管原库或生产库")
    if parsed.get_backend_name() != "mysql" or parsed.host not in ("mysql", "127.0.0.1", "localhost"):
        raise ValueError("仅允许本机MySQL Demo库")


def preflight(session):
    allowed = ((User, "username", {"demo_admin", "demo_dispatcher", *(f"driver{i:02}" for i in range(1, 6))}),
               (Vehicle, "code", {f"VH-{i:03}" for i in range(1, 5)}),
               (Store, "code", {f"ST-YL-{i:03}" for i in range(1, 8)}),
               (Route, "code", {f"RT-YL-{i:02}" for i in range(1, 4)}),
               (Terrain, "code", {"NORMAL", "CONTROLLED", "STRICT"}))
    for model, field, values in allowed:
        if session.scalar(select(model.id).where(getattr(model, field).not_in(values))):
            raise ConflictError(f"目标库包含非精简Demo {model.__name__}，禁止覆盖或删除")


def demand_input(day, row, stores):
    index, period, quantity = row
    return DeliveryDemandCreate(date=day, store_id=stores[index - 1].id,
                                period=period, quantity=quantity)


def seed_compact_demo(session, day, password, *, local_demo=False, prepare_history=False):
    if not local_demo or len(password) < 8:
        raise ValueError("仅限明确的本地Demo；通过环境变量提供至少8位密码")
    preflight(session)
    actor = None
    for username, role in (("demo_admin", UserRole.ADMIN), ("demo_dispatcher", UserRole.DISPATCHER)):
        user = session.scalar(select(User).where(User.username == username))
        if user and (user.role != role or not user.is_active):
            raise ConflictError("演示账号角色冲突或已停用")
        user = user or AuthService(session).create_user(username, password, role)
        if role == UserRole.ADMIN:
            actor = user
    scheduling = DriverSchedulingService(session)
    drivers = []
    for i, name in enumerate(DRIVERS, 1):
        user = session.scalar(select(User).where(User.username == f"driver{i:02}"))
        if user and (user.role != UserRole.DRIVER or not user.is_active):
            raise ConflictError("司机账号角色冲突或已停用")
        drivers.append(user or scheduling.create_driver(DriverCreateInput(username=f"driver{i:02}", display_name=name, password=password), actor))
    terrains = []
    for code, label in (("NORMAL", "普通"), ("CONTROLLED", "中控"), ("STRICT", "严控")):
        terrain = session.scalar(select(Terrain).where(Terrain.code == code))
        terrains.append(terrain or TerrainService(session).create(TerrainCreate(code=code, name=label)))
    types = {}
    for index, (code, label, minimum, maximum) in enumerate(TYPE_CONFIG):
        vehicle_type = session.scalar(select(VehicleType).where(VehicleType.code == code))
        if vehicle_type and (vehicle_type.min_load != minimum or vehicle_type.max_load != maximum or not vehicle_type.is_active):
            raise ConflictError("车型参数已人工修改，Seed不覆盖")
        if vehicle_type is None:
            vehicle_type = VehicleTypeService(session).create(VehicleTypeCreate(code=code, name=label, min_load=minimum, max_load=maximum))
            for terrain in terrains[:index + 1]:
                VehicleTypeTerrainPermissionService(session).add(vehicle_type.id, terrain.id)
        types[code] = vehicle_type
    vehicles = []
    for i, code in enumerate(("FOUR_METER", "BIG_VAN", "SMALL_VAN", "SMALL_VAN"), 1):
        vehicle = session.scalar(select(Vehicle).where(Vehicle.code == f"VH-{i:03}"))
        if vehicle and (vehicle.driver_user_id != drivers[i - 1].id or vehicle.vehicle_type_id != types[code].id or not vehicle.is_active):
            raise ConflictError("车辆绑定或状态已人工变更，Seed不覆盖")
        vehicles.append(vehicle or VehicleService(session).create(VehicleCreate(code=f"VH-{i:03}", plate_number=f"湘AD1{i:03}", vehicle_type_id=types[code].id, driver_user_id=drivers[i - 1].id), actor))
    routes = []
    for i, name in enumerate(("岳麓北线", "河西核心配送线", "洋湖含浦配送线"), 1):
        route = session.scalar(select(Route).where(Route.code == f"RT-YL-{i:02}"))
        route = route or RouteService(session).create(RouteCreate(code=f"RT-YL-{i:02}", name=name))
        if not session.scalar(select(RouteTerrainConfig.id).where(RouteTerrainConfig.route_id == route.id)):
            RouteTerrainService(session).create(route.id, RouteTerrainCreate(terrain_id=terrains[i - 1].id, effective_date=day - timedelta(days=1)))
        routes.append(route)
    stores = []
    for i, (name, address, longitude, latitude, route_index) in enumerate(STORES, 1):
        store = session.scalar(select(Store).where(Store.code == f"ST-YL-{i:03}"))
        store = store or StoreService(session).create(StoreCreate(code=f"ST-YL-{i:03}", name=name, address=address + "（虚构Demo门店）", longitude=longitude, latitude=latitude))
        route = routes[route_index - 1]
        if not session.scalar(select(StoreRoute.store_id).where(StoreRoute.store_id == store.id, StoreRoute.route_id == route.id)):
            StoreRouteService(session).add(store.id, route.id)
        stores.append(store)
    for driver in drivers:
        for period in ("MORNING", "AFTERNOON"):
            if not scheduling.repository.fixed_attendance(day - timedelta(days=1), period, driver.id):
                scheduling.set_fixed_attendance(driver.id, FixedAttendanceInput(effective_date=day - timedelta(days=1), period=period, available=True), actor)
    for check_day in ([day - timedelta(days=1), day] if prepare_history else [day]):
        for vehicle in vehicles:
            if not scheduling.repository.vehicle_attendance(check_day, vehicle.id):
                VehicleAttendanceService(session).create(VehicleAttendanceCreate(date=check_day, vehicle_id=vehicle.id, available=True))
            for period in ("MORNING", "AFTERNOON"):
                if not scheduling.repository.for_vehicle(check_day, period, vehicle.id):
                    scheduling.assign(ScheduleInput(date=check_day, period=period, vehicle_id=vehicle.id, driver_id=vehicle.driver_user_id), actor)
    for row in DEMANDS:
        data = demand_input(day, row, stores)
        if not session.scalar(select(DeliveryDemand.id).where(DeliveryDemand.date == day, DeliveryDemand.store_id == data.store_id, DeliveryDemand.period == data.period)):
            DeliveryDemandService(session).create(data, actor)
    if prepare_history:
        history_day = day - timedelta(days=1)
        if not session.scalar(select(DispatchPlan.id).where(DispatchPlan.delivery_date == history_day)):
            for row in ((3, "MORNING", 50), (4, "MORNING", 60)):
                data = demand_input(history_day, row, stores)
                if not session.scalar(select(DeliveryDemand.id).where(DeliveryDemand.date == history_day, DeliveryDemand.store_id == data.store_id, DeliveryDemand.period == data.period)):
                    DeliveryDemandService(session).create(data, actor)
            generated = AutoDispatchService(session).dispatch(AutoDispatchRequest(date=history_day), actor)
            plan = DispatchPlanService(session).publish(generated.plan_id, actor)
            for index, order in enumerate(plan.orders):
                driver = session.get(User, order.actual_driver_id)
                service = DriverService(session)
                service.start(order.id, driver)
                for stop in order.details:
                    if index == 0:
                        service.arrive_stop(order.id, stop.id, driver)
                        service.sign_stop(order.id, stop.id, DeliveryStopSignRequest(receiver_name="Demo收货员", remark="历史正常签收演示"), driver)
                    else:
                        service.fail_stop(order.id, stop.id, DeliveryStopFailRequest(failure_reason="STORE_CLOSED", remark="虚构历史闭店场景"), driver)
                service.complete(order.id, driver)
    return {"date": day.isoformat(), "accounts": ["demo_admin", "demo_dispatcher", *(d.username for d in drivers)],
            "vehicles": [{"id": v.id, "code": v.code, "plate": v.plate_number, "driver": drivers[i].username} for i, v in enumerate(vehicles)],
            "stores": [{"id": s.id, "code": s.code, "name": s.name, "route": routes[STORES[i][4] - 1].code} for i, s in enumerate(stores)],
            "preseed_demands": len(DEMANDS), "ai_reserved_demands": len(AI_DEMANDS),
            "history_enabled": prepare_history, "standby": drivers[4].username}


def main():
    from app.core.config import get_settings
    from app.infrastructure.database.session import SessionLocal
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-demo", action="store_true", required=True)
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--prepare-history", action="store_true")
    args = parser.parse_args()
    validate_target(get_settings().database_url, args.local_demo, args.expected_database)
    with SessionLocal() as session:
        result = seed_compact_demo(session, args.date, os.environ.get("DEMO_SEED_PASSWORD", ""), local_demo=True, prepare_history=args.prepare_history)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
