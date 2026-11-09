import asyncio

import pytest
from sqlalchemy import func, select

from app.agent.read_only_tools import (
    GetVehicleAttendanceTool,
    ListDeliveryDemandsTool,
    ListDispatchPlansTool,
)
from app.agent.schemas.tool import (
    GetVehicleAttendanceArgs,
    ListDeliveryDemandsArgs,
    ListDispatchPlansArgs,
)
from app.agent.tool_execution import AgentToolContext
from app.domain.enums import UserRole
from app.models.delivery_demand import DeliveryDemand
from app.models.dispatch_plan import DispatchPlan
from app.models.route import Route
from app.models.store import Store
from app.models.vehicle import Vehicle
from app.schemas.auto_dispatch import AutoDispatchRequest
from app.schemas.delivery_demand import DeliveryDemandCreate
from app.schemas.store import StoreCreate
from app.schemas.vehicle_attendance import VehicleAttendanceUpdate
from tests.legacy_support.prepare_interview_demo import DAY, safe_target, seed
from app.services.auth_service import AuthService
from app.services.auto_dispatch_service import AutoDispatchService
from app.services.delivery_demand_service import DeliveryDemandService
from app.services.dispatch_context_service import DispatchContextService
from app.services.dispatch_plan_service import DispatchPlanService
from app.services.store_service import StoreRouteService, StoreService
from app.services.vehicle_attendance_service import VehicleAttendanceService


def setup(session):
    actor = AuthService(session).create_user('demo-admin', 'test-only-password', UserRole.ADMIN)
    seed(session, actor, 'test-only-password')
    return actor


def test_master_seed_is_idempotent_and_preserves_reserved_data(session):
    actor = setup(session)
    first = seed(session, actor, 'not-used-existing-password')
    assert first['vehicles'] == 4 and first['stores'] == 5
    assert session.scalar(select(func.count()).select_from(Vehicle)) == 4
    assert session.scalar(select(func.count()).select_from(Store)) == 5
    assert session.scalar(select(func.count()).select_from(DeliveryDemand)) == 0
    assert session.scalar(select(func.count()).select_from(DispatchPlan)) == 0
    assert session.scalar(select(Store).where(Store.name == '梅溪湖二店')) is None
    assert session.scalar(select(Vehicle).where(Vehicle.plate_number == '湘A12345')) is None


def test_five_demands_greedy_and_vehicle_absence_in_test_database_only(session):
    actor = setup(session)
    # These requests exist only in pytest's disposable in-memory database.
    stores = list(session.scalars(select(Store).order_by(Store.id)))
    # Validate the manual create + separate route-link action with a test-only name.
    manual = StoreService(session).create(StoreCreate(code='TEST-MANUAL', name='测试新增门店'))
    strict = session.scalar(select(Route).where(Route.code == 'INT-RT-3'))
    StoreRouteService(session).add(manual.id, strict.id)
    stores.append(manual)
    for store_index, amount in [(0, 180), (2, 300), (3, 200), (5, 180), (1, 900)]:
        DeliveryDemandService(session).create(DeliveryDemandCreate(date=DAY, store_id=stores[store_index].id, period='MORNING', quantity=amount), actor)
    first = AutoDispatchService(session).dispatch(AutoDispatchRequest(date=DAY), actor)
    assert sum(len(t.stores) for t in first.trips) == 4
    assert len(first.unassigned_demands) == 1
    assert first.unassigned_demands[0].quantity == 900
    assert first.unassigned_demands[0].reasons
    before = DispatchContextService(session).load(DAY)
    vehicle = session.scalar(select(Vehicle).where(Vehicle.plate_number == '湘A12344'))
    attendance = VehicleAttendanceService(session).repository.get_by_date_vehicle(DAY, vehicle.id)
    VehicleAttendanceService(session).update(attendance.id, VehicleAttendanceUpdate(available=False))
    after = DispatchContextService(session).load(DAY)
    assert before.snapshot_version != after.snapshot_version
    second = AutoDispatchService(session).dispatch(AutoDispatchRequest(date=DAY), actor)
    assert second.version == first.version + 1
    assert all(t.vehicle.id != vehicle.id for t in second.trips)
    assert sum(len(t.stores) for t in second.trips) == 1
    context = AgentToolContext(actor)
    demands = asyncio.run(ListDeliveryDemandsTool(DeliveryDemandService(session)).execute(ListDeliveryDemandsArgs(date=DAY), context))
    attendance_result = asyncio.run(GetVehicleAttendanceTool(VehicleAttendanceService(session)).execute(GetVehicleAttendanceArgs(date=DAY), context))
    plans = asyncio.run(ListDispatchPlansTool(DispatchPlanService(session)).execute(ListDispatchPlansArgs(delivery_date=DAY), context))
    assert demands.data['returned_count'] == 5
    assert attendance_result.data['returned_count'] == 4
    assert plans.data['returned_count'] == 2


def test_seed_safety_rejects_unknown_target(tmp_path):
    with pytest.raises(ValueError):
        safe_target(tmp_path)
