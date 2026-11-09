"""Add only interview master data to the Step 9 dedicated SQLite demo."""

if __name__ == "__main__":
    raise SystemExit("RETIRED_TEST_FIXTURE_ONLY: archived demonstration CLI is disabled")

import json
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

DAY = date(2026, 11, 12)
EFFECTIVE = date(2026, 10, 12)
TYPES = (("FOUR_METER", "4.2米厢式货车", 630, 800, 1),
         ("BIG_VAN", "大型面包车", 300, 420, 2),
         ("SMALL_VAN", "小型面包车", 1, 300, 3))
ROUTES = ("岳麓常规配送线", "麓谷园区配送线", "梅溪湖特殊配送线")
STORES = (
    ("洋湖配送店", 0, "长沙市岳麓区洋湖片区·演示商圈A-01（模拟地址）", "演示联系人-洋湖", "0731-5550-0101"),
    ("观沙岭配送店", 0, "长沙市岳麓区观沙岭片区·演示商圈A-02（模拟地址）", "演示联系人-观沙岭", "0731-5550-0102"),
    ("麓谷科技园店", 1, "长沙市岳麓区麓谷科技园片区·演示园区B-01（模拟地址）", "演示联系人-麓谷", "0731-5550-0201"),
    ("大学城配送店", 1, "长沙市岳麓区大学城片区·演示商圈B-02（模拟地址）", "演示联系人-大学城", "0731-5550-0202"),
    ("梅溪湖配送店", 2, "长沙市岳麓区梅溪湖片区·演示商圈C-01（模拟地址）", "演示联系人-梅溪湖", "0731-5550-0301"),
)


def safe_target(root):
    folder = root / ".validation-v11" / "step9-local"
    target = folder / "demo.sqlite3"
    if not target.resolve().is_relative_to(root.resolve() / ".validation-v11" / "step9-local"):
        raise ValueError("数据库解析路径越过专用演示目录")
    if folder.is_symlink() or target.is_symlink() or not target.is_file():
        raise ValueError("先运行独立 Demo 启动模块；拒绝不存在或符号链接数据库")
    credential = folder / "credentials.json"
    if credential.is_symlink():
        raise ValueError("拒绝链接凭据")
    credentials = json.loads(credential.read_text(encoding="utf-8"))
    if credentials.get("username") != "demo-admin":
        raise ValueError("不是 Step9 演示账号")
    with sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True) as source:
        users = source.execute("SELECT username,role FROM users").fetchall()
        if ("demo-admin", "ADMIN") not in users or any(
            name != "demo-admin" and name not in {f"interview-driver{i}" for i in range(1, 6)}
            for name, _ in users
        ):
            raise ValueError("数据库含未识别账号，不接管混合环境")
        if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("数据库完整性检查失败")
        backup = folder / f"before-interview-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.sqlite3"
        with sqlite3.connect(backup) as destination:
            source.backup(destination)
    return target, backup, credentials


def seed(session, actor, password):
    from sqlalchemy import select

    from app.models.route import Route, RouteTerrainConfig
    from app.models.store import Store, StoreRoute
    from app.models.terrain import Terrain
    from app.models.user import User
    from app.models.vehicle import Vehicle, VehicleType, VehicleTypeTerrainPermission
    from app.schemas.driver_scheduling import (
        DriverCreateInput,
        FixedAttendanceInput,
        ScheduleInput,
    )
    from app.schemas.route import RouteCreate, RouteTerrainCreate
    from app.schemas.store import StoreCreate
    from app.schemas.terrain import TerrainCreate
    from app.schemas.vehicle import VehicleCreate, VehicleTypeCreate
    from app.schemas.vehicle_attendance import VehicleAttendanceCreate
    from app.services.driver_scheduling_service import DriverSchedulingService
    from app.services.route_service import RouteService, RouteTerrainService
    from app.services.store_service import StoreRouteService, StoreService
    from app.services.terrain_service import TerrainService
    from app.services.vehicle_attendance_service import VehicleAttendanceService
    from app.services.vehicle_service import (
        VehicleService,
        VehicleTypeService,
        VehicleTypeTerrainPermissionService,
    )

    def find(model, **values):
        return session.scalar(select(model).filter_by(**values))

    def match(row, **expected):
        if row and any(getattr(row, key) != value for key, value in expected.items()):
            raise ValueError(f"{type(row).__name__} 已存在但属性不同，拒绝覆盖")
        return row

    # Validate all unique master identities before the first service commit.
    for code, name, minimum, maximum, _ in TYPES:
        match(find(VehicleType, code=code), name=name, min_load=minimum, max_load=maximum, is_active=True)
    for i, name in enumerate(ROUTES, 1):
        match(find(Route, code=f"INT-RT-{i}"), name=name, is_active=True)
    for i, (name, _, _, _, _) in enumerate(STORES, 1):
        match(find(Store, code=f"INT-ST-{i}"), name=name, is_active=True)

    terrains = []
    for code, name in (("NORMAL", "普通"), ("CONTROLLED", "中控"), ("STRICT", "严控")):
        row = match(find(Terrain, code=code), name=name, is_active=True)
        terrains.append(row or TerrainService(session).create(TerrainCreate(code=code, name=name)))
    types = {}
    for code, name, minimum, maximum, terrain_count in TYPES:
        row = find(VehicleType, code=code) or VehicleTypeService(session).create(
            VehicleTypeCreate(code=code, name=name, min_load=minimum, max_load=maximum))
        allowed = {t.id for t in terrains[:terrain_count]}
        existing = {p.terrain_id for p in session.scalars(select(VehicleTypeTerrainPermission).where(VehicleTypeTerrainPermission.vehicle_type_id == row.id))}
        if existing - allowed:
            raise ValueError("车型已有额外地形许可，不覆盖人工配置")
        for terrain_id in allowed - existing:
            VehicleTypeTerrainPermissionService(session).add(row.id, terrain_id)
        types[code] = row
    scheduling = DriverSchedulingService(session)
    drivers = []
    for i in range(1, 6):
        username = f"interview-driver{i}"
        row = find(User, username=username)
        if row and (row.role.value != "DRIVER" or not row.is_active):
            raise ValueError("司机自然键冲突或停用，不覆盖")
        row = row or scheduling.create_driver(DriverCreateInput(username=username, display_name=f"演示司机{i}", password=password), actor)
        drivers.append(row)
        for period in ("MORNING", "AFTERNOON"):
            if not scheduling.repository.fixed_attendance(DAY, period, row.id):
                scheduling.set_fixed_attendance(row.id, FixedAttendanceInput(effective_date=DAY, period=period, available=True), actor)
    vehicles = []
    for i, code in enumerate(("FOUR_METER", "FOUR_METER", "BIG_VAN", "SMALL_VAN"), 1):
        plate = f"湘A1234{i}"
        row = find(Vehicle, plate_number=plate)
        match(row, code=f"INT-VH-{i}", vehicle_type_id=types[code].id, driver_user_id=drivers[i - 1].id, is_active=True)
        row = row or VehicleService(session).create(VehicleCreate(code=f"INT-VH-{i}", plate_number=plate, vehicle_type_id=types[code].id, driver_user_id=drivers[i - 1].id), actor)
        vehicles.append(row)
        if not scheduling.repository.vehicle_attendance(DAY, row.id):
            VehicleAttendanceService(session).create(VehicleAttendanceCreate(date=DAY, vehicle_id=row.id, available=True))
        for period in ("MORNING", "AFTERNOON"):
            if not scheduling.repository.for_vehicle(DAY, period, row.id):
                scheduling.assign(ScheduleInput(date=DAY, period=period, vehicle_id=row.id, driver_id=drivers[i - 1].id), actor)
    routes = []
    for i, name in enumerate(ROUTES, 1):
        row = find(Route, code=f"INT-RT-{i}") or RouteService(session).create(RouteCreate(code=f"INT-RT-{i}", name=name))
        configs = list(session.scalars(select(RouteTerrainConfig).where(RouteTerrainConfig.route_id == row.id)))
        if configs and not any(c.effective_date <= DAY and c.terrain_id == terrains[i - 1].id for c in configs):
            raise ValueError("已有线路地形配置不同，不覆盖")
        if not any(c.effective_date <= EFFECTIVE for c in configs):
            RouteTerrainService(session).create(row.id, RouteTerrainCreate(terrain_id=terrains[i - 1].id, effective_date=EFFECTIVE))
        routes.append(row)
    stores = []
    for i, (name, route_index, address, contact_name, contact_phone) in enumerate(STORES, 1):
        row = find(Store, code=f"INT-ST-{i}")
        if row is None:
            row = StoreService(session).create(StoreCreate(code=f"INT-ST-{i}", name=name, address=address,
                                                            contact_name=contact_name, contact_phone=contact_phone))
        elif row.name == name and row.address in (None, "", "虚构面试门店（不用于真实配送）"):
            # Repair only known seed placeholders; preserve any address edited by a user.
            row.address = address
            if not row.contact_name:
                row.contact_name = contact_name
            if not row.contact_phone:
                row.contact_phone = contact_phone
            session.commit()
        links = list(session.scalars(select(StoreRoute).where(StoreRoute.store_id == row.id)))
        if not links:
            StoreRouteService(session).add(row.id, routes[route_index].id)
        # Preserve existing route links. The page already shows their effective
        # configuration, and reseeding must not silently rewrite user changes.
        stores.append(row)
    return {"date": DAY.isoformat(), "routes": len(routes), "stores": len(stores), "vehicles": len(vehicles),
            "drivers": len(drivers), "created_demands": 0,
            "binding": [{"plate": v.plate_number, "driver": drivers[i].username, "type": v.vehicle_type.code,
                         "min_kg": str(v.vehicle_type.min_load), "max_kg": str(v.vehicle_type.max_load)} for i, v in enumerate(vehicles)]}


def main():
    root = Path(__file__).resolve().parents[3]
    target, backup, credentials = safe_target(root)
    os.environ.update(DATABASE_URL="sqlite+pysqlite:///" + target.as_posix(), JWT_SECRET_KEY=credentials["jwt_secret"])
    from app.infrastructure.database.session import SessionLocal
    from app.repositories.user_repository import UserRepository
    with SessionLocal() as session:
        result = seed(session, UserRepository(session).get_by_username("demo-admin"), credentials["password"])
    print(json.dumps({"database": str(target), "backup": str(backup), **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
