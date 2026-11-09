"""Read-only queries for a date-scoped dispatch exception snapshot."""

from datetime import date

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload

from app.domain.enums import DeliveryDemandStatus, DispatchPlanStatus
from app.models.delivery_demand import DeliveryDemand
from app.models.dispatch_plan import DispatchOrder, DispatchOrderDetail, DispatchPlan
from app.models.vehicle_attendance import VehicleAttendance


class DailyExceptionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def reference_plan_id(self, delivery_date: date) -> int | None:
        for status in (DispatchPlanStatus.PUBLISHED, DispatchPlanStatus.DRAFT):
            statement = (
                select(DispatchPlan.id)
                .where(
                    DispatchPlan.delivery_date == delivery_date,
                    DispatchPlan.status == status,
                )
                .order_by(DispatchPlan.version.desc())
                .limit(1)
            )
            plan_id = self.session.scalar(statement)
            if plan_id is not None:
                return plan_id
        return None

    def planning_demands(self, delivery_date: date) -> list[DeliveryDemand]:
        # Match the existing re-dispatch eligibility: PLANNED is reusable only
        # when an active DRAFT actually contains the demand.
        assigned_to_draft = (
            select(DispatchOrderDetail.id)
            .join(DispatchOrder, DispatchOrder.id == DispatchOrderDetail.dispatch_order_id)
            .join(DispatchPlan, DispatchPlan.id == DispatchOrder.plan_id)
            .where(
                DispatchOrderDetail.delivery_demand_id == DeliveryDemand.id,
                DispatchPlan.delivery_date == delivery_date,
                DispatchPlan.status == DispatchPlanStatus.DRAFT,
            )
            .exists()
        )
        statement = (
            select(DeliveryDemand)
            .options(joinedload(DeliveryDemand.store))
            .where(
                DeliveryDemand.date == delivery_date,
                or_(
                    DeliveryDemand.status == DeliveryDemandStatus.PENDING,
                    and_(
                        DeliveryDemand.status == DeliveryDemandStatus.PLANNED,
                        assigned_to_draft,
                    ),
                ),
            )
            .order_by(DeliveryDemand.id)
        )
        return list(self.session.scalars(statement))

    def attendance_by_vehicle(
        self, delivery_date: date, vehicle_ids: set[int]
    ) -> dict[int, VehicleAttendance]:
        if not vehicle_ids:
            return {}
        statement = select(VehicleAttendance).where(
            VehicleAttendance.date == delivery_date,
            VehicleAttendance.vehicle_id.in_(vehicle_ids),
        )
        return {item.vehicle_id: item for item in self.session.scalars(statement)}
