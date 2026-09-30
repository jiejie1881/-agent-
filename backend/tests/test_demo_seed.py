from sqlalchemy import func, select

from app.domain.enums import DeliveryDemandStatus, DispatchPlanStatus, UserRole
from app.models.delivery_demand import DeliveryDemand
from app.models.dispatch_plan import DispatchPlan
from app.models.user import User
from app.models.vehicle_attendance import VehicleAttendance
from app.scripts.seed_demo import DEMO_DATE, seed_demo


def test_demo_seed_is_idempotent_and_uses_real_dispatch(session):
    first = seed_demo(session)
    second = seed_demo(session)

    assert first.created_plan is True
    assert second.created_plan is False
    assert first.plan.id == second.plan.id
    assert first.plan.version == 1
    assert first.plan.status == DispatchPlanStatus.DRAFT

    users = list(
        session.scalars(
            select(User).where(User.username.like("demo_%")).order_by(User.username)
        )
    )
    assert [(user.username, user.role) for user in users] == [
        ("demo_admin", UserRole.ADMIN),
        ("demo_dispatcher", UserRole.DISPATCHER),
        ("demo_viewer", UserRole.VIEWER),
    ]

    assert len(first.terrains) == 3
    assert len(first.routes) == 5
    assert len(first.stores) == 13
    assert len(first.vehicle_types) == 3
    assert len(first.vehicles) == 8

    attendance = list(
        session.scalars(
            select(VehicleAttendance).where(VehicleAttendance.date == DEMO_DATE)
        )
    )
    assert len(attendance) == 8
    assert sum(item.available for item in attendance) == 6

    demands = list(
        session.scalars(
            select(DeliveryDemand).where(DeliveryDemand.date == DEMO_DATE)
        )
    )
    assert len(demands) == 16
    assert all(item.store.longitude is not None for item in demands)
    assert all(item.store.latitude is not None for item in demands)
    assert sum(item.status == DeliveryDemandStatus.PLANNED for item in demands) >= 1

    plans = session.scalar(
        select(func.count(DispatchPlan.id)).where(
            DispatchPlan.delivery_date == DEMO_DATE
        )
    )
    assert plans == 1
    assert len(first.plan.orders) > 0
    assert len(first.plan.orders) >= 1
