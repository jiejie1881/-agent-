"""Opt-in local enterprise Demo. Add missing records only; never reset or delete."""

if __name__ == "__main__":
    raise SystemExit("RETIRED_TEST_FIXTURE_ONLY: archived demonstration CLI is disabled")

import argparse
import os
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.engine import make_url
from app.core.config import get_settings
from app.infrastructure.database.session import SessionLocal
from app.domain.enums import UserRole, VehicleTypeCode, DeliveryPeriod
from app.domain.exceptions import ConflictError
from app.models.user import User
from app.models.vehicle import Vehicle, VehicleType
from app.models.store import Store, StoreRoute
from app.models.route import Route, RouteTerrainConfig
from app.models.terrain import Terrain
from app.models.delivery_demand import DeliveryDemand
from app.models.vehicle_attendance import VehicleAttendance
from app.models.dispatch_plan import DispatchPlan
from app.models.driver_scheduling import DriverLeave, DriverSubstitution
from app.schemas.driver_scheduling import DriverCreateInput, AttendanceInput, ScheduleInput
from app.schemas.driver_leave import LeaveRequestInput, LeaveReviewInput, SubstitutionInput
from app.schemas.vehicle import VehicleCreate, VehicleTypeCreate
from app.schemas.terrain import TerrainCreate
from app.schemas.store import StoreCreate
from app.schemas.route import RouteCreate, RouteTerrainCreate
from app.schemas.vehicle_attendance import VehicleAttendanceCreate
from app.schemas.delivery_demand import DeliveryDemandCreate
from app.schemas.auto_dispatch import AutoDispatchRequest
from app.schemas.driver import DeliveryStopSignRequest
from app.services.auth_service import AuthService
from app.services.vehicle_service import VehicleService, VehicleTypeService, VehicleTypeTerrainPermissionService
from app.services.terrain_service import TerrainService
from app.services.store_service import StoreService, StoreRouteService
from app.services.route_service import RouteService, RouteTerrainService
from app.services.vehicle_attendance_service import VehicleAttendanceService
from app.services.driver_scheduling_service import DriverSchedulingService
from app.services.driver_leave_service import DriverLeaveService
from app.services.delivery_demand_service import DeliveryDemandService
from app.services.auto_dispatch_service import AutoDispatchService
from app.services.dispatch_plan_service import DispatchPlanService
from app.services.driver_service import DriverService

NAMESPACE = 'ENTDEMO_'
NAMES = ('张建军', '李志强', '王海波', '陈志远', '刘国强', '周晓峰', '赵明远', '孙启航')
STORE_NAMES = ('岳麓一店', '岳麓二店', '河西一店', '河西二店', '梅溪湖一店', '洋湖一店', '望城坡一店')
ROUTE_NAMES = ('岳麓北线', '岳麓南线', '河西核心配送线', '梅溪湖配送线', '洋湖配送线')

def validate_target(url, local_demo, expected_database):
    parsed = make_url(url)
    if not local_demo or parsed.database != expected_database or 'prod' in (parsed.database or '').lower():
        raise ValueError('必须显式确认本地Demo环境及准确数据库名；禁止生产库')
    if parsed.get_backend_name() != 'sqlite' and parsed.host not in ('localhost', '127.0.0.1', 'mysql'):
        raise ValueError('只允许本机或本项目Compose mysql目标')

def seed_enterprise_demo(session, day, password, *, local_demo=False, prepare_history=False):
    if not local_demo or len(password) < 8:
        raise ValueError('仅允许显式本地Demo；初始密码至少8位，不重置已有账号')
    # Shared enum/load configuration is an existing business dependency, not seed-owned.
    types = {v.code: v for v in session.scalars(select(VehicleType))}
    if any(not v.is_active for v in types.values()):
        raise ConflictError('现有车型已停用；Seed不会自动启用或覆盖配置')
    # Refuse a mixed-date scenario before creating plans or altering attendance.
    for check_day in ([day, day-timedelta(days=1)] if prepare_history else [day]):
        foreign = session.scalar(select(DeliveryDemand.id).join(Store).where(DeliveryDemand.date == check_day, ~Store.code.startswith(NAMESPACE)))
        if foreign:
            raise ConflictError('该日期含非企业Demo需求，请选择空日期，不覆盖手工业务')
        foreign_vehicle = session.scalar(select(VehicleAttendance.id).join(Vehicle).where(VehicleAttendance.date == check_day, VehicleAttendance.available.is_(True), ~Vehicle.code.startswith(NAMESPACE)))
        if foreign_vehicle:
            raise ConflictError('该日期已有其他出勤车辆，请选择独立Demo日期')
        for plan in session.scalars(select(DispatchPlan).where(DispatchPlan.delivery_date == check_day)):
            if not plan.orders or any(not o.vehicle.code.startswith(NAMESPACE) for o in plan.orders):
                raise ConflictError('该日期已有非企业Demo或空方案；禁止接管历史版本')
    for code, label, minimum, maximum in ((VehicleTypeCode.FOUR_METER,'4.2米厢式货车',630,800), (VehicleTypeCode.BIG_VAN,'大型面包车',300,420), (VehicleTypeCode.SMALL_VAN,'小型面包车',1,300)):
        if code not in types:
            types[code] = VehicleTypeService(session).create(VehicleTypeCreate(code=code,name=label,min_load=minimum,max_load=maximum))
    users = []
    for username, role in (('enterprise_admin',UserRole.ADMIN), ('enterprise_dispatcher',UserRole.DISPATCHER), ('enterprise_viewer',UserRole.VIEWER)):
        existing = session.scalar(select(User).where(User.username == username))
        if existing and (existing.role != role or not existing.is_active):
            raise ConflictError('演示账号被其他角色占用或停用，停止而非重置')
        users.append(existing or AuthService(session).create_user(username,password,role))
    actor = users[0]
    scheduling = DriverSchedulingService(session)
    drivers = []
    for i, name in enumerate(NAMES,1):
        username = f'enterprise_driver{i:03}'
        driver = session.scalar(select(User).where(User.username == username))
        if driver and (driver.role != UserRole.DRIVER or not driver.is_active):
            raise ConflictError('演示司机账号冲突，禁止换绑/重置')
        drivers.append(driver or scheduling.create_driver(DriverCreateInput(username=username,display_name=name,password=password),actor))
    vehicles = []
    for i, code in enumerate((VehicleTypeCode.FOUR_METER,VehicleTypeCode.FOUR_METER,VehicleTypeCode.BIG_VAN,VehicleTypeCode.BIG_VAN,VehicleTypeCode.SMALL_VAN,VehicleTypeCode.SMALL_VAN),1):
        business_code = f'ENTDEMO_VH_{i:03}'
        vehicle = session.scalar(select(Vehicle).where(Vehicle.code == business_code))
        if vehicle is None:
            vehicle = VehicleService(session).create(VehicleCreate(code=business_code,plate_number=f'湘AE9{i:03}',vehicle_type_id=types[code].id,driver_user_id=drivers[i-1].id),actor)
        if (vehicle.driver_user_id != drivers[i-1].id or not vehicle.is_active
                or vehicle.plate_number != f'湘AE9{i:03}' or vehicle.vehicle_type_id != types[code].id):
            raise ConflictError('演示车已人工换绑/停用；保持现状，请换日期或人工核查')
        vehicles.append(vehicle)
    terrain = session.scalar(select(Terrain).where(Terrain.code == 'ENTDEMO_NORMAL'))
    terrain = terrain or TerrainService(session).create(TerrainCreate(code='ENTDEMO_NORMAL',name='企业演示普通区'))
    for v in types.values():
        service = VehicleTypeTerrainPermissionService(session)
        if not any(p.terrain_id == terrain.id for p in service.list(v.id)):
            service.add(v.id,terrain.id)  # New dedicated terrain; no existing permissions removed.
    routes = []
    for i, name in enumerate(ROUTE_NAMES,1):
        route = session.scalar(select(Route).where(Route.code == f'ENTDEMO_RT_YL_{i:02}'))
        route = route or RouteService(session).create(RouteCreate(code=f'ENTDEMO_RT_YL_{i:02}',name=name+'（企业演示）'))
        if i < 5 and not session.scalar(select(RouteTerrainConfig).where(RouteTerrainConfig.route_id == route.id)):
            RouteTerrainService(session).create(route.id,RouteTerrainCreate(terrain_id=terrain.id,effective_date=day-timedelta(days=1)))
        routes.append(route)
    stores = []
    for i, name in enumerate(STORE_NAMES,1):
        store = session.scalar(select(Store).where(Store.code == f'ENTDEMO_ST_YL_{i:03}'))
        store = store or StoreService(session).create(StoreCreate(code=f'ENTDEMO_ST_YL_{i:03}',name=name+'（企业演示）',address='长沙市岳麓区（虚构企业演示门店，未定位）'))
        route = routes[min((i-1)//2,3)] if i < 7 else routes[4]
        if not session.scalar(select(StoreRoute).where(StoreRoute.store_id == store.id,StoreRoute.route_id == route.id)):
            StoreRouteService(session).add(store.id,route.id)
        stores.append(store)
    # A real multi-route boundary store enables a legal, demonstrable manual move.
    if not session.scalar(select(StoreRoute).where(StoreRoute.store_id == stores[4].id,StoreRoute.route_id == routes[0].id)):
        StoreRouteService(session).add(stores[4].id,routes[0].id)
    for check_day in ([day, day-timedelta(days=1)] if prepare_history else [day]):
        for v in vehicles:
            existing = session.scalar(select(VehicleAttendance).where(VehicleAttendance.date == check_day,VehicleAttendance.vehicle_id == v.id))
            if not existing:
                VehicleAttendanceService(session).create(VehicleAttendanceCreate(date=check_day,vehicle_id=v.id,available=True))
        for d in drivers:
            for period in ('MORNING','AFTERNOON'):
                if not scheduling.repository.attendance(check_day,period,d.id):
                    scheduling.set_attendance(AttendanceInput(driver_id=d.id,date=check_day,period=period,available=True),actor)
        for v in vehicles:
            for period in ('MORNING','AFTERNOON'):
                if not scheduling.repository.for_vehicle(check_day,period,v.id):
                    scheduling.assign(ScheduleInput(date=check_day,period=period,vehicle_id=v.id,driver_id=v.driver_user_id),actor)
    leave_service = DriverLeaveService(session)
    leave = session.scalar(select(DriverLeave).where(DriverLeave.driver_id == drivers[1].id,DriverLeave.start_date == day,DriverLeave.end_date == day,DriverLeave.period == 'MORNING'))
    if not leave:
        leave = leave_service.submit(LeaveRequestInput(start_date=day,end_date=day,period='MORNING',reason='企业Demo虚构请假',leave_type='OTHER'),actor,drivers[1].id)
        leave_service.review(leave.id,LeaveReviewInput(decision='APPROVED',review_remark='企业演示经正式Service审批'),actor)
        proposal = leave_service.propose(SubstitutionInput(leave_request_id=leave.id,vehicle_id=vehicles[1].id,substitute_driver_id=drivers[6].id,date=day,period='MORNING'),actor)
        leave_service.confirm(proposal.id,actor)
    # Never silently approve an existing pending/cancelled leave or substitution on a rerun.
    if leave.status != 'APPROVED' or scheduling.resolve_effective_driver(vehicles[1].id,day,'MORNING')['effective_driver_id'] != drivers[6].id:
        raise ConflictError('既有演示请假/代班已变化，Seed保持不变，请管理员核查')
    for i, quantity in enumerate((700,700,350,350,60,60,120)):
        if not session.scalar(select(DeliveryDemand).where(DeliveryDemand.date == day,DeliveryDemand.store_id == stores[i].id,DeliveryDemand.period == DeliveryPeriod.MORNING)):
            DeliveryDemandService(session).create(DeliveryDemandCreate(date=day,store_id=stores[i].id,period='MORNING',quantity=quantity),actor)
    plans = list(session.scalars(select(DispatchPlan).where(DispatchPlan.delivery_date == day).order_by(DispatchPlan.version)))
    if not plans:
        AutoDispatchService(session).dispatch(AutoDispatchRequest(date=day),actor)
        plans = list(session.scalars(select(DispatchPlan).where(DispatchPlan.delivery_date == day)))
    if prepare_history:
        history_day = day-timedelta(days=1)
        existing_plan = session.scalar(select(DispatchPlan).where(DispatchPlan.delivery_date == history_day))
        if not existing_plan:
            for store in stores[:2]:
                if not session.scalar(select(DeliveryDemand).where(DeliveryDemand.date == history_day,DeliveryDemand.store_id == store.id,DeliveryDemand.period == DeliveryPeriod.MORNING)):
                    DeliveryDemandService(session).create(DeliveryDemandCreate(date=history_day,store_id=store.id,period='MORNING',quantity=50),actor)
            result = AutoDispatchService(session).dispatch(AutoDispatchRequest(date=history_day),actor)
            plan = DispatchPlanService(session).publish(result.plan_id,actor)
            for order in plan.orders:
                driver = session.get(User,order.actual_driver_id)
                service = DriverService(session)
                service.start(order.id,driver)
                for stop in order.details:
                    service.arrive_stop(order.id,stop.id,driver)
                    service.sign_stop(order.id,stop.id,DeliveryStopSignRequest(receiver_name='虚构演示收货人',remark='企业Demo正常签收'),driver)
                service.complete(order.id,driver)
    return {'date': day.isoformat(), 'vehicle_codes': [v.code for v in vehicles],
            'driver_accounts': [d.username for d in drivers], 'store_names': [s.name for s in stores],
            'plan_ids': [p.id for p in plans], 'leave_id': leave.id,
            'notices': ['所有姓名/账号/牌号为虚构；没有电话或伪造地图坐标', '洋湖演示线故意缺少地形配置以展示未分配原因', '既有记录不重置；失败后可补缺重试，但不保证跨多个Service整批回滚']}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--local-demo',action='store_true',required=True)
    parser.add_argument('--expected-database',required=True)
    parser.add_argument('--date',type=date.fromisoformat,default=date(2026,11,6))
    parser.add_argument('--prepare-history',action='store_true')
    args = parser.parse_args()
    validate_target(get_settings().database_url,args.local_demo,args.expected_database)
    password = os.environ.get('DEMO_SEED_PASSWORD','')
    if len(password) < 8:
        raise SystemExit('请通过本地环境变量DEMO_SEED_PASSWORD提供至少8位演示初始密码；不读取或重置已有密码')
    with SessionLocal() as session:
        import json
        print(json.dumps(seed_enterprise_demo(session,args.date,password,local_demo=True,prepare_history=args.prepare_history),ensure_ascii=False))

if __name__ == '__main__':
    main()
