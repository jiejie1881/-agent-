from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models.vehicle import Vehicle
from app.models.user import User
from app.models.dispatch_plan import DispatchPlan, DispatchOrder, DispatchOrderDetail
from app.models.driver_scheduling import DriverLeave, DriverSubstitution
from app.models.vehicle_attendance import VehicleAttendance
from app.domain.enums import UserRole, DispatchPlanStatus

class EnterpriseRepository:
    def __init__(self, session):
        self.session = session

    def vehicles(self):
        return list(self.session.scalars(select(Vehicle).options(selectinload(Vehicle.vehicle_type), selectinload(Vehicle.driver)).order_by(Vehicle.id)))

    def drivers(self):
        return list(self.session.scalars(select(User).where(User.role == UserRole.DRIVER).order_by(User.id)))

    def plans(self, day):
        return list(self.session.scalars(select(DispatchPlan).where(DispatchPlan.delivery_date == day, DispatchPlan.status == DispatchPlanStatus.PUBLISHED).options(
            selectinload(DispatchPlan.orders).selectinload(DispatchOrder.route),
            selectinload(DispatchPlan.orders).selectinload(DispatchOrder.details).selectinload(DispatchOrderDetail.delivery_demand)).order_by(DispatchPlan.version)))

    def attendance(self, day):
        return {r.vehicle_id: r.available for r in self.session.scalars(select(VehicleAttendance).where(VehicleAttendance.date == day))}

    def leaves(self, day):
        return list(self.session.scalars(select(DriverLeave).where(DriverLeave.start_date <= day, DriverLeave.end_date >= day).order_by(DriverLeave.id)))

    def substitutions(self, day):
        return list(self.session.scalars(select(DriverSubstitution).where(DriverSubstitution.date == day).order_by(DriverSubstitution.id)))
