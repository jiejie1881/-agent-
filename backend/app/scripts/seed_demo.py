"""Create the repeatable local Demo data set without deleting existing data."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain.enums import (
    DeliveryDemandStatus,
    DeliveryPeriod,
    UserRole,
    VehicleTypeCode,
)
from app.domain.exceptions import ConflictError
from app.infrastructure.database.session import SessionLocal
from app.models.dispatch_plan import DispatchPlan
from app.models.route import Route
from app.models.store import Store
from app.models.terrain import Terrain
from app.models.user import User
from app.models.vehicle import Vehicle, VehicleType
from app.repositories.delivery_demand_repository import DeliveryDemandRepository
from app.repositories.dispatch_plan_repository import DispatchPlanRepository
from app.repositories.route_repository import RouteRepository, RouteTerrainRepository
from app.repositories.store_repository import StoreRepository, StoreRouteRepository
from app.repositories.terrain_repository import TerrainRepository
from app.repositories.user_repository import UserRepository
from app.repositories.vehicle_attendance_repository import VehicleAttendanceRepository
from app.repositories.vehicle_repository import (
    VehicleRepository,
    VehicleTypeRepository,
    VehicleTypeTerrainPermissionRepository,
)
from app.schemas.auto_dispatch import AutoDispatchRequest
from app.schemas.delivery_demand import DeliveryDemandCreate, DeliveryDemandUpdate
from app.schemas.route import RouteCreate, RouteTerrainCreate, RouteTerrainUpdate, RouteUpdate
from app.schemas.store import StoreCreate, StoreUpdate
from app.schemas.terrain import TerrainCreate
from app.schemas.vehicle import VehicleCreate, VehicleTypeCreate
from app.schemas.vehicle_attendance import VehicleAttendanceCreate
from app.services.auth_service import AuthService
from app.services.auto_dispatch_service import AutoDispatchService
from app.services.delivery_demand_service import DeliveryDemandService
from app.services.dispatch_plan_service import DispatchPlanService
from app.services.route_service import RouteService, RouteTerrainService
from app.services.store_service import StoreRouteService, StoreService
from app.services.terrain_service import TerrainService
from app.services.vehicle_attendance_service import VehicleAttendanceService
from app.services.vehicle_service import (
    VehicleService,
    VehicleTypeService,
    VehicleTypeTerrainPermissionService,
)

DEMO_DATE = date(2026, 10, 3)
DEFAULT_DEMO_PASSWORD = "Demo123456"


@dataclass(frozen=True)
class DemoSeedSummary:
    users: tuple[User, ...]
    terrains: tuple[Terrain, ...]
    routes: tuple[Route, ...]
    stores: tuple[Store, ...]
    vehicle_types: tuple[VehicleType, ...]
    vehicles: tuple[Vehicle, ...]
    plan: DispatchPlan
    created_plan: bool


def _get_or_create_user(
    session: Session, username: str, role: UserRole, password: str
) -> User:
    repository = UserRepository(session)
    existing = repository.get_by_username(username)
    if existing is not None:
        if existing.role != role:
            raise ConflictError(f"Demo 用户 {username} 已存在，但角色不是 {role.value}")
        return existing
    return AuthService(session).create_user(username, password, role)


def _get_or_create_terrain(
    session: Session, code: str, name: str, description: str
) -> Terrain:
    repository = TerrainRepository(session)
    existing = repository.get_by_code(code) or repository.get_by_name(name)
    if existing is not None:
        return existing
    return TerrainService(session).create(
        TerrainCreate(code=code, name=name, description=description)
    )


def _get_or_create_route(
    session: Session, code: str, name: str, legacy_code: str | None = None
) -> Route:
    repository = RouteRepository(session)
    existing = repository.get_by_code(code)
    if existing is None and legacy_code is not None:
        existing = repository.get_by_code(legacy_code)
    if existing is not None:
        if existing.code != code or existing.name != name:
            return RouteService(session).update(
                existing.id, RouteUpdate(code=code, name=name)
            )
        return existing
    return RouteService(session).create(
        RouteCreate(code=code, name=name, description="本地 Demo 配送线路")
    )


def _ensure_route_terrain(
    session: Session, route: Route, terrain: Terrain
) -> None:
    repository = RouteTerrainRepository(session)
    existing = repository.get_by_route_and_date(route.id, DEMO_DATE)
    if existing is None:
        RouteTerrainService(session).create(
            route.id,
            RouteTerrainCreate(terrain_id=terrain.id, effective_date=DEMO_DATE),
        )
    elif existing.terrain_id != terrain.id:
        RouteTerrainService(session).update(
            route.id, existing.id, RouteTerrainUpdate(terrain_id=terrain.id)
        )


def _get_or_create_store(
    session: Session,
    code: str,
    name: str,
    address: str,
    longitude: Decimal,
    latitude: Decimal,
    route: Route,
) -> Store:
    repository = StoreRepository(session)
    store = repository.get_by_code(code)
    if store is None:
        store = StoreService(session).create(
            StoreCreate(
                code=code,
                name=name,
                address=address,
                contact_name="Demo 联系人",
                contact_phone="13800000000",
                longitude=longitude,
                latitude=latitude,
            )
        )
    else:
        store = StoreService(session).update(
            store.id,
            StoreUpdate(
                name=name,
                address=address,
                longitude=longitude,
                latitude=latitude,
            ),
        )
    route_service = StoreRouteService(session)
    for link in list(route_service.list(store.id)):
        if link.route_id != route.id:
            route_service.remove(store.id, link.route_id)
    if StoreRouteRepository(session).get_link(store.id, route.id) is None:
        route_service.add(store.id, route.id)
    return store


def _get_or_create_vehicle_type(
    session: Session,
    code: VehicleTypeCode,
    name: str,
    min_load: Decimal,
    max_load: Decimal,
) -> VehicleType:
    repository = VehicleTypeRepository(session)
    existing = repository.get_by_code(code)
    if existing is not None:
        return existing
    return VehicleTypeService(session).create(
        VehicleTypeCreate(
            code=code,
            name=name,
            min_load=min_load,
            max_load=max_load,
        )
    )


def _ensure_vehicle_permission(
    session: Session, vehicle_type: VehicleType, terrain: Terrain
) -> None:
    repository = VehicleTypeTerrainPermissionRepository(session)
    if repository.get_permission(vehicle_type.id, terrain.id) is None:
        VehicleTypeTerrainPermissionService(session).add(
            vehicle_type.id, terrain.id
        )


def _get_or_create_vehicle(
    session: Session,
    code: str,
    plate_number: str,
    vehicle_type: VehicleType,
) -> Vehicle:
    repository = VehicleRepository(session)
    existing = repository.get_by_code(code)
    if existing is not None:
        return existing
    return VehicleService(session).create(
        VehicleCreate(
            code=code,
            plate_number=plate_number,
            vehicle_type_id=vehicle_type.id,
        )
    )


def _ensure_attendance(session: Session, vehicle: Vehicle, available: bool) -> None:
    repository = VehicleAttendanceRepository(session)
    existing = repository.get_by_date_vehicle(DEMO_DATE, vehicle.id)
    if existing is None:
        VehicleAttendanceService(session).create(
            VehicleAttendanceCreate(
                date=DEMO_DATE, vehicle_id=vehicle.id, available=available
            )
        )
    elif existing.available != available:
        raise ConflictError(f"车辆 {vehicle.code} 在 Demo 日期已有不同出勤状态")


def _ensure_demands(
    session: Session,
    actor: User,
    store_by_code: dict[str, Store],
    specs: tuple[tuple[str, DeliveryPeriod, str], ...],
) -> None:
    repository = DeliveryDemandRepository(session)
    service = DeliveryDemandService(session)
    desired = [
        (store_by_code[store_code], period, Decimal(quantity))
        for store_code, period, quantity in specs
    ]
    demo_store_ids = {store.id for store in store_by_code.values()}
    existing = [
        demand
        for demand in repository.list_filtered(DEMO_DATE, None, None, 0, 100)
        if demand.store_id in demo_store_ids
    ]
    by_key = {(item.store_id, item.period): item for item in existing}
    desired_keys = {(store.id, period) for store, period, _ in desired}
    obsolete = [item for item in existing if (item.store_id, item.period) not in desired_keys]
    missing = [item for item in desired if (item[0].id, item[1]) not in by_key]

    # Reuse obsolete DEMO demand records first. This preserves IDs and avoids
    # deleting records referenced by the cancelled historical Demo plan.
    for demand, (store, period, quantity) in zip(obsolete, missing):
        service.update(
            demand.id,
            DeliveryDemandUpdate(
                store_id=store.id, period=period, quantity=quantity
            ),
            actor,
        )
        by_key[(store.id, period)] = demand
    missing = missing[len(obsolete):]

    for store, period, quantity in desired:
        demand = by_key.get((store.id, period))
        if demand is None:
            continue
        if demand.quantity != quantity:
            service.update(
                demand.id, DeliveryDemandUpdate(quantity=quantity), actor
            )
    for store, period, quantity in missing:
        service.create(
            DeliveryDemandCreate(
                date=DEMO_DATE,
                store_id=store.id,
                period=period,
                quantity=quantity,
                status=DeliveryDemandStatus.PENDING,
            ),
            actor,
        )


def seed_demo(session: Session, password: str = DEFAULT_DEMO_PASSWORD) -> DemoSeedSummary:
    """Idempotently fill the DEMO_ data and generate V1 through the real service."""

    users = tuple(
        _get_or_create_user(session, username, role, password)
        for username, role in (
            ("demo_admin", UserRole.ADMIN),
            ("demo_dispatcher", UserRole.DISPATCHER),
            ("demo_viewer", UserRole.VIEWER),
        )
    )
    actor = users[0]

    terrain_by_key = {
        "normal": _get_or_create_terrain(
            session, "DEMO_TERRAIN_NORMAL", "普通区域", "普通配送区域"
        ),
        "controlled": _get_or_create_terrain(
            session, "DEMO_TERRAIN_CONTROLLED", "中控区域", "中控配送区域"
        ),
        "strict": _get_or_create_terrain(
            session, "DEMO_TERRAIN_STRICT", "严控区域", "严控配送区域"
        ),
    }

    route_specs = (
        ("meixi", "DEMO_ROUTE_MEIXI", "梅溪湖配送线", "normal", "DEMO_ROUTE_EAST"),
        ("lugu", "DEMO_ROUTE_LUGU", "麓谷高新配送线", "normal", "DEMO_ROUTE_WEST"),
        ("riverside", "DEMO_ROUTE_RIVERSIDE", "滨江城区配送线", "normal", None),
        ("university", "DEMO_ROUTE_UNIVERSITY", "大学城配送线", "controlled", "DEMO_ROUTE_MOUNTAIN"),
        ("south", "DEMO_ROUTE_SOUTH", "洋湖含浦配送线", "strict", None),
    )
    route_by_key: dict[str, Route] = {}
    for key, code, name, terrain_key, legacy_code in route_specs:
        route = _get_or_create_route(session, code, name, legacy_code)
        _ensure_route_terrain(session, route, terrain_by_key[terrain_key])
        route_by_key[key] = route

    had_map_revision = StoreRepository(session).get_by_code("DEMO_STORE_13") is not None

    # Coordinates were resolved once from public OSM/Nominatim area results
    # and are persisted; the browser never re-geocodes these Demo addresses.
    store_specs = (
        ("DEMO_STORE_01", "梅溪湖中央店", "梅溪湖片区", "112.8907111", "28.1917313", "meixi"),
        ("DEMO_STORE_02", "天顶社区店", "天顶片区", "112.8837300", "28.2051221", "meixi"),
        ("DEMO_STORE_03", "麓谷科技园店", "麓谷片区", "112.8916273", "28.2171916", "lugu"),
        ("DEMO_STORE_04", "东方红产业园店", "东方红片区", "112.8226654", "28.2418796", "lugu"),
        ("DEMO_STORE_05", "观沙岭滨江店", "观沙岭片区", "112.9462766", "28.2360446", "riverside"),
        ("DEMO_STORE_06", "银盆岭中心店", "银盆岭片区", "112.9492807", "28.2255333", "riverside"),
        ("DEMO_STORE_07", "望月湖社区店", "望月湖片区", "112.9470476", "28.2050334", "riverside"),
        ("DEMO_STORE_08", "岳麓大学城店", "岳麓街道片区", "112.9241872", "28.1641497", "university"),
        ("DEMO_STORE_09", "桔子洲西岸店", "桔子洲街道片区", "112.9458440", "28.1682828", "university"),
        ("DEMO_STORE_10", "洋湖新城店", "洋湖片区", "112.9199935", "28.1042711", "south"),
        ("DEMO_STORE_11", "学士工业园店", "学士片区", "112.8664769", "28.1244614", "south"),
        ("DEMO_STORE_12", "含浦综合店", "含浦片区", "112.8512300", "28.1033004", "south"),
        ("DEMO_STORE_13", "坪塘南站店", "坪塘片区", "112.9064375", "28.0896168", "south"),
    )
    store_by_code = {
        code: _get_or_create_store(
            session,
            code,
            name,
            f"长沙市岳麓区{area}（Demo）",
            Decimal(longitude),
            Decimal(latitude),
            route_by_key[route_key],
        )
        for code, name, area, longitude, latitude, route_key in store_specs
    }

    type_by_code = {
        VehicleTypeCode.FOUR_METER: _get_or_create_vehicle_type(
            session,
            VehicleTypeCode.FOUR_METER,
            "4.2米厢式车",
            Decimal("630"),
            Decimal("800"),
        ),
        VehicleTypeCode.BIG_VAN: _get_or_create_vehicle_type(
            session,
            VehicleTypeCode.BIG_VAN,
            "大面包车",
            Decimal("300"),
            Decimal("420"),
        ),
        VehicleTypeCode.SMALL_VAN: _get_or_create_vehicle_type(
            session,
            VehicleTypeCode.SMALL_VAN,
            "小面包车",
            Decimal("1"),
            Decimal("300"),
        ),
    }
    for terrain in terrain_by_key.values():
        _ensure_vehicle_permission(
            session, type_by_code[VehicleTypeCode.SMALL_VAN], terrain
        )
    for terrain_key in ("normal", "controlled"):
        _ensure_vehicle_permission(
            session,
            type_by_code[VehicleTypeCode.BIG_VAN],
            terrain_by_key[terrain_key],
        )
    _ensure_vehicle_permission(
        session,
        type_by_code[VehicleTypeCode.FOUR_METER],
        terrain_by_key["normal"],
    )

    vehicle_specs = (
        ("DEMO_TRUCK_01", "湘A·D4201", VehicleTypeCode.FOUR_METER, True),
        ("DEMO_TRUCK_02", "湘A·D4202", VehicleTypeCode.FOUR_METER, True),
        ("DEMO_BIGVAN_01", "湘A·B3001", VehicleTypeCode.BIG_VAN, True),
        ("DEMO_BIGVAN_02", "湘A·B3002", VehicleTypeCode.BIG_VAN, False),
        ("DEMO_SMALLVAN_01", "湘A·S1001", VehicleTypeCode.SMALL_VAN, True),
        ("DEMO_SMALLVAN_02", "湘A·S1002", VehicleTypeCode.SMALL_VAN, True),
        ("DEMO_SMALLVAN_03", "湘A·S1003", VehicleTypeCode.SMALL_VAN, True),
        ("DEMO_SMALLVAN_04", "湘A·S1004", VehicleTypeCode.SMALL_VAN, False),
    )
    vehicles: list[Vehicle] = []
    for code, plate, type_code, available in vehicle_specs:
        vehicle = _get_or_create_vehicle(
            session, code, plate, type_by_code[type_code]
        )
        _ensure_attendance(session, vehicle, available)
        vehicles.append(vehicle)

    demand_specs = (
        ("DEMO_STORE_01", DeliveryPeriod.MORNING, "260"),
        ("DEMO_STORE_02", DeliveryPeriod.MORNING, "170"),
        ("DEMO_STORE_03", DeliveryPeriod.MORNING, "420"),
        ("DEMO_STORE_04", DeliveryPeriod.MORNING, "310"),
        ("DEMO_STORE_05", DeliveryPeriod.MORNING, "120"),
        ("DEMO_STORE_06", DeliveryPeriod.MORNING, "150"),
        ("DEMO_STORE_08", DeliveryPeriod.MORNING, "110"),
        ("DEMO_STORE_12", DeliveryPeriod.MORNING, "180"),
        ("DEMO_STORE_01", DeliveryPeriod.AFTERNOON, "190"),
        ("DEMO_STORE_03", DeliveryPeriod.AFTERNOON, "350"),
        ("DEMO_STORE_07", DeliveryPeriod.AFTERNOON, "100"),
        ("DEMO_STORE_09", DeliveryPeriod.AFTERNOON, "90"),
        ("DEMO_STORE_10", DeliveryPeriod.AFTERNOON, "210"),
        ("DEMO_STORE_11", DeliveryPeriod.AFTERNOON, "230"),
        ("DEMO_STORE_12", DeliveryPeriod.AFTERNOON, "140"),
        ("DEMO_STORE_13", DeliveryPeriod.AFTERNOON, "160"),
    )
    plan_repository = DispatchPlanRepository(session)
    plans = plan_repository.list(DEMO_DATE, 0, 100)
    # A previous Seed revision used the same date. Preserve its plan history,
    # release its demands through the formal cancellation workflow, then build
    # the YueLu data set and let auto-dispatch create the next version.
    draft_plans = [item for item in plans if item.status.value == "DRAFT"]
    if not had_map_revision and draft_plans and len(plans) == 1 and plans[0].version == 1:
        DispatchPlanService(session).cancel(draft_plans[0].id, actor)

    _ensure_demands(session, actor, store_by_code, demand_specs)

    plans = plan_repository.list(DEMO_DATE, 0, 100)
    current_drafts = [item for item in plans if item.status.value == "DRAFT"]
    created_plan = False
    if current_drafts:
        plan = max(current_drafts, key=lambda item: item.version)
    else:
        result = AutoDispatchService(session).dispatch(
            AutoDispatchRequest(date=DEMO_DATE), actor
        )
        plan = plan_repository.get(result.plan_id)
        assert plan is not None
        created_plan = True

    return DemoSeedSummary(
        users=users,
        terrains=tuple(terrain_by_key.values()),
        routes=tuple(route_by_key.values()),
        stores=tuple(store_by_code.values()),
        vehicle_types=tuple(type_by_code.values()),
        vehicles=tuple(vehicles),
        plan=plan,
        created_plan=created_plan,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="幂等创建本地物流系统 Demo 样本数据"
    )
    parser.add_argument(
        "--password",
        default=os.getenv("DEMO_PASSWORD", DEFAULT_DEMO_PASSWORD),
        help="三个本地 Demo 账号共用密码；也可使用 DEMO_PASSWORD 环境变量",
    )
    args = parser.parse_args()
    with SessionLocal() as session:
        summary = seed_demo(session, args.password)
        plan = summary.plan
        assigned_count = sum(len(order.details) for order in plan.orders)
        print("Demo 数据准备完成（幂等，不清理现有数据）")
        print(f"Demo 日期: {DEMO_DATE}")
        print("Demo 用户: demo_admin, demo_dispatcher, demo_viewer")
        print(f"本地 Demo 默认密码: {args.password}")
        print(
            f"方案: #{plan.id} / V{plan.version} / {plan.status.value} "
            f"({'新生成' if summary.created_plan else '已存在，未重复生成'})"
        )
        print(
            f"任务: {len(plan.orders)}, 已分配需求: {assigned_count}, "
            f"未分配需求: {len(plan.unassigned_demands)}"
        )


if __name__ == "__main__":
    main()
