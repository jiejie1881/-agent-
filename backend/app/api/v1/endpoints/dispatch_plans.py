from datetime import date

from fastapi import APIRouter, Query

from app.api.dependencies import DbSession
from app.api.auth_dependencies import CurrentUser
from app.schemas.dispatch_plan import (
    DispatchDemandMoveRequest,
    DispatchPlanDetailResponse,
    DispatchPlanSummaryResponse,
    PersistedUnassignedDemandResponse,
)
from app.services.dispatch_plan_service import DispatchPlanService

router = APIRouter(prefix="/dispatch-plans", tags=["dispatch-plans"])


@router.get("", response_model=list[DispatchPlanSummaryResponse])
def list_dispatch_plans(
    db: DbSession,
    delivery_date: date | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
):
    return DispatchPlanService(db).list(delivery_date, offset, limit)


@router.get(
    "/by-date/{delivery_date}",
    response_model=list[DispatchPlanSummaryResponse],
)
def list_dispatch_plan_history(
    delivery_date: date,
    db: DbSession,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
):
    return DispatchPlanService(db).list(delivery_date, offset, limit)


@router.get(
    "/by-date/{delivery_date}/versions/{version}",
    response_model=DispatchPlanDetailResponse,
)
def get_dispatch_plan_version(
    delivery_date: date,
    version: int,
    db: DbSession,
):
    return DispatchPlanService(db).get_by_version(delivery_date, version)


@router.get("/{plan_id}", response_model=DispatchPlanDetailResponse)
def get_dispatch_plan(plan_id: int, db: DbSession):
    return DispatchPlanService(db).get(plan_id)


@router.get(
    "/{plan_id}/unassigned",
    response_model=list[PersistedUnassignedDemandResponse],
)
def get_unassigned_demands(plan_id: int, db: DbSession):
    return DispatchPlanService(db).get(plan_id).unassigned_demands


@router.post(
    "/{plan_id}/move-demand", response_model=DispatchPlanDetailResponse
)
def move_dispatch_demand(
    plan_id: int,
    data: DispatchDemandMoveRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    return DispatchPlanService(db).move_demand(plan_id, data, current_user)


@router.post("/{plan_id}/publish", response_model=DispatchPlanDetailResponse)
def publish_dispatch_plan(
    plan_id: int, current_user: CurrentUser, db: DbSession
):
    return DispatchPlanService(db).publish(plan_id, current_user)


@router.post("/{plan_id}/cancel", response_model=DispatchPlanDetailResponse)
def cancel_dispatch_plan(
    plan_id: int, current_user: CurrentUser, db: DbSession
):
    return DispatchPlanService(db).cancel(plan_id, current_user)


@router.post(
    "/{plan_id}/orders/{order_id}/start-delivery",
    response_model=DispatchPlanDetailResponse,
)
def start_dispatch_order_delivery(
    plan_id: int, order_id: int, current_user: CurrentUser, db: DbSession
):
    return DispatchPlanService(db).start_delivery(
        plan_id, order_id, current_user
    )


@router.post(
    "/{plan_id}/orders/{order_id}/complete",
    response_model=DispatchPlanDetailResponse,
)
def complete_dispatch_order_delivery(
    plan_id: int, order_id: int, current_user: CurrentUser, db: DbSession
):
    return DispatchPlanService(db).complete_delivery(
        plan_id, order_id, current_user
    )
