from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.domain.enums import DeliveryDemandStatus, DeliveryStopStatus, UserRole
from app.domain.exceptions import ConflictError
from app.models.delivery_demand import DeliveryDemand
from app.models.dispatch_plan import DispatchOrderDetail, DispatchPlan
from app.models.store import Store, StoreRoute
from app.models.user import User
from app.models.vehicle import Vehicle
from app.scripts.seed_compact_demo import AI_DEMANDS, demand_input, seed_compact_demo, validate_target
from app.schemas.auto_dispatch import AutoDispatchRequest
from app.schemas.driver_leave import LeaveRequestInput, LeaveReviewInput, SubstitutionInput
from app.services.auth_service import AuthService
from app.services.auto_dispatch_service import AutoDispatchService
from app.services.delivery_demand_service import DeliveryDemandService
from app.services.driver_leave_service import DriverLeaveService
from app.services.driver_scheduling_service import DriverSchedulingService

DAY = date(2026, 10, 9)
PASSWORD = "LocalTestPassword123"


@pytest.mark.parametrize("url,flag,expected", [
    ("mysql+pymysql://u@mysql/logistics_dispatch", True, "logistics_dispatch"),
    ("mysql+pymysql://u@remote/logistics_dispatch_demo_compact", True, "logistics_dispatch_demo_compact"),
    ("mysql+pymysql://u@mysql/logistics_dispatch_demo_compact", False, "logistics_dispatch_demo_compact"),
    ("mysql+pymysql://u@mysql/logistics_dispatch_demo_compact", True, "logistics_dispatch_demo_verify"),
])
def test_compact_target_guard(url, flag, expected):
    with pytest.raises(ValueError):
        validate_target(url, flag, expected)


def seed(session, history=False):
    return seed_compact_demo(session, DAY, PASSWORD, local_demo=True, prepare_history=history)


def test_compact_refuses_mixed_database_before_writes(session):
    session.add(Store(code="MANUAL", name="用户门店")); session.commit()
    with pytest.raises(ConflictError):
        seed(session)
    assert session.scalar(select(func.count()).select_from(User)) == 0
    assert session.scalar(select(func.count()).select_from(Vehicle)) == 0


def test_compact_idempotent_relationships_and_login(session):
    first = seed(session)
    counts = {m: session.scalar(select(func.count()).select_from(m)) for m in (User, Vehicle, Store, StoreRoute, DeliveryDemand)}
    assert list(counts.values()) == [7, 4, 7, 7, 8]
    hashes = {u.id: u.password_hash for u in session.scalars(select(User))}
    assert seed(session) == first
    assert all(session.scalar(select(func.count()).select_from(m)) == n for m, n in counts.items())
    assert hashes == {u.id: u.password_hash for u in session.scalars(select(User))}
    for username in first["accounts"]:
        service = AuthService(session)
        token = service.login_driver(username, PASSWORD) if username.startswith("driver") else service.login(username, PASSWORD)
        assert token.access_token
    assert all(s.longitude and s.latitude for s in session.scalars(select(Store)))
    standby = session.scalar(select(User).where(User.username == "driver05"))
    assert not session.scalar(select(Vehicle.id).where(Vehicle.driver_user_id == standby.id))


def test_compact_twelve_demands_allocate_all_four_vehicles(session):
    seed(session)
    admin = session.scalar(select(User).where(User.role == UserRole.ADMIN))
    stores = list(session.scalars(select(Store).order_by(Store.code)))
    for row in AI_DEMANDS:
        DeliveryDemandService(session).create(demand_input(DAY, row, stores), admin)
    result = AutoDispatchService(session).dispatch(AutoDispatchRequest(date=DAY), admin)
    assert not result.unassigned_demands
    assert sum(len(t.stores) for t in result.trips) == 12
    assert len({t.vehicle.id for t in result.trips}) == 4
    v2 = AutoDispatchService(session).dispatch(AutoDispatchRequest(date=DAY), admin)
    assert v2.version == 2 and sum(len(t.stores) for t in v2.trips) == 12
    for trip in result.trips:
        vehicle = session.get(Vehicle, trip.vehicle.id)
        assert vehicle.vehicle_type.min_load <= trip.total_load <= vehicle.vehicle_type.max_load


def test_compact_leave_requires_confirmed_substitution_and_preserves_default(session):
    seed(session)
    admin = session.scalar(select(User).where(User.role == UserRole.ADMIN))
    b = session.scalar(select(User).where(User.username == "driver02"))
    e = session.scalar(select(User).where(User.username == "driver05"))
    vehicle = session.scalar(select(Vehicle).where(Vehicle.code == "VH-002"))
    workflow = DriverLeaveService(session)
    leave = workflow.submit(LeaveRequestInput(start_date=DAY, end_date=DAY, period="MORNING", reason="演示请假"), b)
    workflow.review(leave.id, LeaveReviewInput(decision="APPROVED"), admin)
    dispatch = AutoDispatchService(session).dispatch(AutoDispatchRequest(date=DAY), admin)
    assert all(t.vehicle.id != vehicle.id for t in dispatch.trips if t.period.value == "MORNING")
    assert any("DRIVER_ON_LEAVE_NO_CONFIRMED_SUBSTITUTE" in str(d.reasons) for d in dispatch.unassigned_demands)
    proposal = workflow.propose(SubstitutionInput(leave_request_id=leave.id, vehicle_id=vehicle.id, substitute_driver_id=e.id, date=DAY, period="MORNING"), admin)
    assert DriverSchedulingService(session).resolve_effective_driver(vehicle.id, DAY, "MORNING")["effective_driver_id"] is None
    workflow.confirm(proposal.id, admin)
    assert DriverSchedulingService(session).resolve(DAY, "MORNING", vehicle.id).id == e.id
    result = AutoDispatchService(session).dispatch(AutoDispatchRequest(date=DAY), admin)
    assert not result.unassigned_demands
    assert vehicle.driver_user_id == b.id
    assert DriverSchedulingService(session).resolve(DAY, "AFTERNOON", vehicle.id).id == b.id
    seed(session)  # does not revert approved leave or confirmed substitute
    assert DriverSchedulingService(session).resolve(DAY, "MORNING", vehicle.id).id == e.id


def test_compact_history_is_separate_and_terminal(session):
    seed(session, True)
    stops = list(session.scalars(select(DispatchOrderDetail)))
    assert {s.delivery_status for s in stops} == {DeliveryStopStatus.SIGNED, DeliveryStopStatus.FAILED}
    assert all(s.delivery_demand.status == DeliveryDemandStatus.COMPLETED for s in stops)
    assert session.scalar(select(DispatchPlan.delivery_date)) == DAY - timedelta(days=1)
    assert len(list(session.scalars(select(DeliveryDemand).where(DeliveryDemand.date == DAY, DeliveryDemand.status == DeliveryDemandStatus.PENDING)))) == 8
    counts = [session.scalar(select(func.count()).select_from(m)) for m in (DeliveryDemand, DispatchPlan, DispatchOrderDetail)]
    seed(session, True)
    assert counts == [session.scalar(select(func.count()).select_from(m)) for m in (DeliveryDemand, DispatchPlan, DispatchOrderDetail)]
