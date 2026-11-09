from datetime import date

from fastapi import APIRouter, Query
from fastapi import Header
from pydantic import BaseModel, Field

from app.api.dependencies import DbSession
from app.api.auth_dependencies import CurrentUser
from app.schemas.dispatch_plan import (
    DispatchDemandMoveRequest,
    DispatchPlanDetailResponse,
    DispatchPlanSummaryResponse,
    PersistedUnassignedDemandResponse,
)
from app.services.dispatch_plan_service import DispatchPlanService
from app.services.agent_publish_preview_service import AgentPublishPreviewService
from app.services.agent_draft_adjustment_service import AgentDraftAdjustmentService

class AgentDemandMoveRequest(DispatchDemandMoveRequest):
    expected_plan_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')

router = APIRouter(prefix="/dispatch-plans", tags=["dispatch-plans"])

@router.post('/{plan_id}/agent-move-demand', response_model=DispatchPlanDetailResponse)
def agent_move(plan_id: int, data: AgentDemandMoveRequest, current_user: CurrentUser, db: DbSession):
    return AgentDraftAdjustmentService(db.get_bind()).move(plan_id, DispatchDemandMoveRequest(**data.model_dump(exclude={'expected_plan_sha256'})), data.expected_plan_sha256, current_user.id)


class AgentPublishConfirmation(BaseModel):
    confirmation_receipt: str = Field(min_length=20, max_length=2048)
    confirmed: bool


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


@router.get("/{plan_id}/agent-publish-preview")
def preview_agent_publish(plan_id: int, current_user: CurrentUser, db: DbSession):
    return AgentPublishPreviewService(db).preview(plan_id, current_user)


@router.post("/{plan_id}/agent-confirm-publish", response_model=DispatchPlanDetailResponse)
def confirm_agent_publish(plan_id: int, data: AgentPublishConfirmation,
                          current_user: CurrentUser, db: DbSession,
                          idempotency_key: str = Header(alias="Idempotency-Key")):
    from app.core.config import get_settings
    from app.services.agent_publish_service import AgentPublishService

    return AgentPublishService(db.get_bind(), get_settings()).confirm(
        plan_id, data.confirmation_receipt, idempotency_key,
        data.confirmed, current_user.id)


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
