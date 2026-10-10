from sqlalchemy import select
from app.models.driver_scheduling import DriverLeave, DriverSubstitution
from app.models.dispatch_plan import DispatchOrder, DispatchPlan
from app.domain.enums import DispatchPlanStatus


class DriverLeaveRepository:
    def __init__(self, session):
        self.session = session

    def leaves(self, driver_id=None):
        query = select(DriverLeave).order_by(DriverLeave.id.desc())
        if driver_id is not None:
            query = query.where(DriverLeave.driver_id == driver_id)
        return list(self.session.scalars(query))

    def substitutions(self):
        return list(self.session.scalars(select(DriverSubstitution).order_by(DriverSubstitution.id.desc())))

    def substitution(self, row_id, *, lock=False):
        stmt = select(DriverSubstitution).where(DriverSubstitution.id == row_id)
        return self.session.scalar(stmt.with_for_update() if lock else stmt)

    def confirmed(self, day, period, vehicle_id):
        return self.session.scalar(select(DriverSubstitution).where(DriverSubstitution.date == day, DriverSubstitution.period == period, DriverSubstitution.vehicle_id == vehicle_id, DriverSubstitution.status == "CONFIRMED"))

    def driver_orders(self, driver_id, start, end, period=None):
        stmt = select(DispatchOrder).join(DispatchPlan).where(
            DispatchOrder.actual_driver_id == driver_id,
            DispatchPlan.delivery_date.between(start, end),
            DispatchPlan.status == DispatchPlanStatus.PUBLISHED,
        )
        if period and period != "ALL_DAY":
            stmt = stmt.where(DispatchOrder.period == period)
        return list(self.session.scalars(stmt))
