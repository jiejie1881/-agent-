from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.dispatch_engine.models import DispatchEngineResult
from app.domain.enums import DispatchPlanStatus
from app.models.delivery_demand import DeliveryDemand
from app.models.dispatch_plan import (
    DispatchOrder,
    DispatchOrderDetail,
    DeliveryProof,
    DispatchPlan,
    DispatchPlanUnassignedDemand,
)
from app.models.vehicle import Vehicle


class DispatchPlanRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def next_version(self, delivery_date: date) -> int:
        statement = select(func.max(DispatchPlan.version)).where(
            DispatchPlan.delivery_date == delivery_date
        )
        current = self.session.scalar(statement)
        return (current or 0) + 1

    def save_result(
        self,
        result: DispatchEngineResult,
        version: int,
        status: DispatchPlanStatus,
    ) -> DispatchPlan:
        plan = DispatchPlan(
            delivery_date=result.dispatch_date,
            version=version,
            status=status,
        )
        self.session.add(plan)
        self.session.flush()

        for trip in result.trips:
            order = DispatchOrder(
                plan_id=plan.id,
                vehicle_id=trip.vehicle.id,
                period=trip.period,
                trip_no=trip.trip_no,
                route_id=trip.route.id,
                total_load=trip.total_load,
            )
            self.session.add(order)
            self.session.flush()
            for item in trip.demands:
                self.session.add(
                    DispatchOrderDetail(
                        dispatch_order_id=order.id,
                        delivery_demand_id=item.demand.id,
                        quantity=item.quantity,
                    )
                )

        for item in result.unassigned_demands:
            self.session.add(
                DispatchPlanUnassignedDemand(
                    plan_id=plan.id,
                    delivery_demand_id=item.demand.id,
                    reasons=list(item.reasons),
                )
            )

        self.session.flush()
        return plan

    def get(self, plan_id: int) -> DispatchPlan | None:
        statement = self._detail_statement().where(DispatchPlan.id == plan_id)
        return self.session.scalar(statement)

    def get_for_update(self, plan_id: int) -> DispatchPlan | None:
        statement = (
            self._detail_statement()
            .where(DispatchPlan.id == plan_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self.session.scalar(statement)

    def get_by_date_version(
        self, delivery_date: date, version: int
    ) -> DispatchPlan | None:
        statement = self._detail_statement().where(
            DispatchPlan.delivery_date == delivery_date,
            DispatchPlan.version == version,
        )
        return self.session.scalar(statement)

    def get_published_by_date(
        self, delivery_date: date, exclude_plan_id: int | None = None
    ) -> DispatchPlan | None:
        statement = self._detail_statement().where(
            DispatchPlan.delivery_date == delivery_date,
            DispatchPlan.status == DispatchPlanStatus.PUBLISHED,
        )
        if exclude_plan_id is not None:
            statement = statement.where(DispatchPlan.id != exclude_plan_id)
        return self.session.scalar(statement.with_for_update())

    def assigned_demand_ids_in_draft_plans(
        self,
        delivery_date: date,
        demand_ids: set[int],
        exclude_plan_id: int | None = None,
    ) -> set[int]:
        if not demand_ids:
            return set()
        statement = (
            select(DispatchOrderDetail.delivery_demand_id)
            .join(
                DispatchOrder,
                DispatchOrder.id == DispatchOrderDetail.dispatch_order_id,
            )
            .join(DispatchPlan, DispatchPlan.id == DispatchOrder.plan_id)
            .where(
                DispatchOrderDetail.delivery_demand_id.in_(demand_ids),
                DispatchPlan.delivery_date == delivery_date,
                DispatchPlan.status == DispatchPlanStatus.DRAFT,
            )
            .distinct()
        )
        if exclude_plan_id is not None:
            statement = statement.where(DispatchPlan.id != exclude_plan_id)
        return set(self.session.scalars(statement))

    def list(
        self,
        delivery_date: date | None,
        offset: int,
        limit: int,
    ) -> list[DispatchPlan]:
        statement = select(DispatchPlan)
        if delivery_date is not None:
            statement = statement.where(
                DispatchPlan.delivery_date == delivery_date
            )
        statement = (
            statement.order_by(
                DispatchPlan.delivery_date.desc(), DispatchPlan.version.desc()
            )
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def set_status(
        self, plan: DispatchPlan, status: DispatchPlanStatus
    ) -> DispatchPlan:
        plan.status = status
        self.session.add(plan)
        self.session.flush()
        return plan

    @staticmethod
    def _detail_statement():
        return select(DispatchPlan).options(
            selectinload(DispatchPlan.orders).selectinload(DispatchOrder.details)
            .selectinload(DispatchOrderDetail.proofs).selectinload(DeliveryProof.reviews),
            selectinload(DispatchPlan.orders)
            .joinedload(DispatchOrder.vehicle)
            .joinedload(Vehicle.vehicle_type),
            selectinload(DispatchPlan.orders).joinedload(DispatchOrder.route),
            selectinload(DispatchPlan.orders)
            .selectinload(DispatchOrder.details)
            .joinedload(DispatchOrderDetail.delivery_demand)
            .joinedload(DeliveryDemand.store),
            selectinload(DispatchPlan.unassigned_demands)
            .joinedload(DispatchPlanUnassignedDemand.delivery_demand)
            .joinedload(DeliveryDemand.store),
        )
