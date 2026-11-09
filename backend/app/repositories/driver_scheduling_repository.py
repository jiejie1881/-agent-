from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.driver_scheduling import DriverAttendance, DriverAttendanceRule, DriverLeave, DriverSchedule
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_attendance import VehicleAttendance
from app.models.dispatch_plan import DispatchOrder, DispatchPlan
from app.domain.enums import UserRole


class DriverSchedulingRepository:
    def __init__(self, session: Session):
        self.session = session

    def drivers(self):
        return list(self.session.scalars(select(User).where(User.role == UserRole.DRIVER).order_by(User.id)))

    def vehicles(self):
        return list(self.session.scalars(select(Vehicle).order_by(Vehicle.id)))

    def lock_driver(self, driver_id, *, for_update=True):
        stmt = select(User).where(User.id == driver_id)
        return self.session.scalar(stmt.with_for_update().execution_options(populate_existing=True) if for_update else stmt)

    def lock_vehicle(self, vehicle_id, *, for_update=True):
        stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
        return self.session.scalar(stmt.with_for_update().execution_options(populate_existing=True) if for_update else stmt)

    def schedules(self, day=None, driver_id=None):
        stmt = select(DriverSchedule).order_by(DriverSchedule.date.desc(), DriverSchedule.id)
        if day is not None:
            stmt = stmt.where(DriverSchedule.date == day)
        if driver_id is not None:
            stmt = stmt.where(DriverSchedule.driver_id == driver_id)
        return list(self.session.scalars(stmt))

    def schedule(self, schedule_id, *, for_update=True):
        stmt = select(DriverSchedule).where(DriverSchedule.id == schedule_id)
        return self.session.scalar(stmt.with_for_update() if for_update else stmt)

    def for_vehicle(self, day, period, vehicle_id):
        return self.session.scalar(select(DriverSchedule).where(DriverSchedule.date == day, DriverSchedule.period == period, DriverSchedule.vehicle_id == vehicle_id))

    def for_driver(self, day, period, driver_id):
        return self.session.scalar(select(DriverSchedule).where(DriverSchedule.date == day, DriverSchedule.period == period, DriverSchedule.driver_id == driver_id))

    def attendance(self, day, period, driver_id):
        return self.session.scalar(select(DriverAttendance).where(DriverAttendance.date == day, DriverAttendance.period == period, DriverAttendance.driver_id == driver_id))

    def fixed_attendance(self, day, period, driver_id):
        return self.session.scalar(select(DriverAttendanceRule).where(
            DriverAttendanceRule.driver_id == driver_id,
            DriverAttendanceRule.period == period,
            DriverAttendanceRule.effective_date <= day,
        ).order_by(DriverAttendanceRule.effective_date.desc()).limit(1))

    def vehicle_attendance(self, day, vehicle_id):
        return self.session.scalar(select(VehicleAttendance).where(VehicleAttendance.date == day, VehicleAttendance.vehicle_id == vehicle_id))

    def on_leave(self, day, period, driver_id):
        return self.leave_for_shift(day, period, driver_id) is not None

    def leave_for_shift(self, day, period, driver_id):
        return self.session.scalar(select(DriverLeave).where(DriverLeave.driver_id == driver_id, DriverLeave.status.in_(["PENDING", "APPROVED"]), DriverLeave.start_date <= day, DriverLeave.end_date >= day, DriverLeave.period.in_([period, "ALL_DAY"])).order_by(DriverLeave.id).limit(1))

    def leave(self, leave_id, *, for_update=False):
        stmt = select(DriverLeave).where(DriverLeave.id == leave_id)
        return self.session.scalar(stmt.with_for_update() if for_update else stmt)

    def leaves(self):
        return list(self.session.scalars(select(DriverLeave).order_by(DriverLeave.id.desc())))

    def orders(self, day, period, vehicle_id, *, for_update=True):
        stmt = select(DispatchOrder).join(DispatchPlan).where(DispatchPlan.delivery_date == day, DispatchOrder.period == period, DispatchOrder.vehicle_id == vehicle_id, DispatchPlan.status.in_(["DRAFT", "PUBLISHED"]))
        return list(self.session.scalars(stmt.with_for_update() if for_update else stmt))

    def default_vehicle(self, driver_id, *, for_update=True):
        stmt = select(Vehicle).where(Vehicle.driver_user_id == driver_id)
        return self.session.scalar(stmt.with_for_update() if for_update else stmt)

    def add(self, row):
        self.session.add(row)
        self.session.flush()
        return row
