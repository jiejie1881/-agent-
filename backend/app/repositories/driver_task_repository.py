from datetime import date

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.domain.enums import (
    DeliveryDemandStatus,
    DeliveryStopStatus,
    DispatchPlanStatus,
)
from app.models.delivery_demand import DeliveryDemand
from app.models.dispatch_plan import (
    DeliveryProof,
    DispatchOrder,
    DispatchOrderDetail,
    DispatchPlan,
)
from app.models.vehicle import Vehicle


class DriverTaskRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_for_driver(self, task_id: int, driver_user_id: int) -> DispatchOrder | None:
        return self.session.scalar(
            self._statement()
            .where(
                DispatchOrder.id == task_id,
                DispatchOrder.actual_driver_id == driver_user_id,
                self._visible_plan_or_completed_task(),
            )
        )

    def list_for_driver(
        self,
        driver_user_id: int,
        *,
        delivery_date: date | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[DispatchOrder], int]:
        filters = [
            DispatchOrder.actual_driver_id == driver_user_id,
            self._visible_plan_or_completed_task(),
        ]
        if delivery_date is not None:
            filters.append(DispatchPlan.delivery_date == delivery_date)
        if date_from is not None:
            filters.append(DispatchPlan.delivery_date >= date_from)
        if date_to is not None:
            filters.append(DispatchPlan.delivery_date <= date_to)

        count_statement = (
            select(func.count(DispatchOrder.id))
            .join(DispatchPlan, DispatchPlan.id == DispatchOrder.plan_id)
            .join(Vehicle, Vehicle.id == DispatchOrder.vehicle_id)
            .where(*filters)
        )
        total = self.session.scalar(count_statement) or 0
        statement = (
            self._statement()
            .where(*filters)
            .order_by(
                DispatchPlan.delivery_date.desc(),
                DispatchOrder.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement).unique()), total

    @staticmethod
    def _visible_plan_or_completed_task():
        # A replaced plan is CANCELLED, but its completed tasks remain historical
        # records owned by the original driver. Never expose unexecuted old tasks.
        has_details = select(DispatchOrderDetail.id).where(
            DispatchOrderDetail.dispatch_order_id == DispatchOrder.id
        ).correlate(DispatchOrder).exists()
        unfinished = select(DispatchOrderDetail.id).join(
            DeliveryDemand, DeliveryDemand.id == DispatchOrderDetail.delivery_demand_id
        ).where(
            DispatchOrderDetail.dispatch_order_id == DispatchOrder.id,
            or_(DeliveryDemand.status != DeliveryDemandStatus.COMPLETED,
                DispatchOrderDetail.delivery_status.not_in(
                    [DeliveryStopStatus.SIGNED, DeliveryStopStatus.FAILED])),
        ).correlate(DispatchOrder).exists()
        return or_(
            DispatchPlan.status == DispatchPlanStatus.PUBLISHED,
            and_(DispatchPlan.status == DispatchPlanStatus.CANCELLED,
                 has_details, ~unfinished),
        )

    @staticmethod
    def _statement():
        return (
            select(DispatchOrder)
            .join(DispatchPlan, DispatchPlan.id == DispatchOrder.plan_id)
            .join(Vehicle, Vehicle.id == DispatchOrder.vehicle_id)
            .options(
                joinedload(DispatchOrder.plan),
                joinedload(DispatchOrder.vehicle).joinedload(Vehicle.vehicle_type),
                joinedload(DispatchOrder.route),
                selectinload(DispatchOrder.details)
                .joinedload(DispatchOrderDetail.delivery_demand)
                .joinedload(DeliveryDemand.store),
                selectinload(DispatchOrder.details).selectinload(
                    DispatchOrderDetail.proofs
                ).selectinload(DeliveryProof.reviews),
            )
        )
