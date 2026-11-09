"""Read-only publication review for an Agent-origin draft."""
import hashlib
import json

from sqlalchemy.orm import Session

from app.domain.enums import DispatchPlanStatus
from app.domain.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.domain.permissions import Permission, has_permission
from app.models.agent_dispatch_acceptance import AgentDispatchPlanSource
from app.repositories.dispatch_plan_repository import DispatchPlanRepository
from app.services.dispatch_context_service import DispatchContextService
from app.services.dispatch_plan_publication_validator import DispatchPlanPublicationValidator
from app.services.dispatch_validation_service import DispatchValidationService
from app.services.agent_publish_receipt import issue_publish_receipt
from app.core.config import get_settings


def persisted_plan_digest(plan) -> str:
    payload = {
        "plan_id": plan.id, "date": plan.delivery_date.isoformat(), "version": plan.version,
        "status": plan.status.value,
        "orders": [{
            "id": o.id, "vehicle_id": o.vehicle_id, "driver_id": o.actual_driver_id,
            "period": o.period.value, "trip_no": o.trip_no, "route_id": o.route_id,
            "total_load": str(o.total_load),
            "details": sorted((d.delivery_demand_id, str(d.quantity)) for d in o.details),
        } for o in sorted(plan.orders, key=lambda item: item.id)],
        "unassigned": sorted((u.delivery_demand_id, tuple(u.reasons))
                             for u in plan.unassigned_demands),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AgentPublishPreviewService:
    def __init__(self, session: Session):
        self.session = session

    def preview(self, plan_id: int, actor) -> dict:
        if not actor.is_active or not has_permission(actor.role, Permission.DISPATCH_WRITE):
            raise PermissionDeniedError()
        plan = DispatchPlanRepository(self.session).get(plan_id)
        if plan is None:
            raise NotFoundError("派车方案不存在")
        source = self.session.get(AgentDispatchPlanSource, plan_id)
        if source is None:
            raise NotFoundError("Agent 草稿不存在")
        if plan.status != DispatchPlanStatus.DRAFT:
            raise ConflictError("只有 Agent 草稿可以预览发布")
        current = DispatchContextService(self.session).load(plan.delivery_date)
        issues = DispatchPlanPublicationValidator(DispatchValidationService(self.session)).validate(
            plan, for_update=False)
        stale = current.snapshot_version != source.post_save_snapshot_version
        allowed = has_permission(actor.role, Permission.AGENT_PLAN_PUBLISH)
        digest = persisted_plan_digest(plan)
        can_confirm = allowed and not stale and not issues
        return {
            "plan_id": plan.id, "delivery_date": plan.delivery_date,
            "version": plan.version, "plan_sha256": digest,
            "saved_snapshot_version": source.post_save_snapshot_version,
            "current_snapshot_version": current.snapshot_version,
            "stale": stale, "validation_issues": issues,
            "can_confirm_publish": can_confirm,
            "can_adjust_draft": get_settings().agent_draft_accept_enabled and has_permission(actor.role,Permission.AGENT_DRAFT_ACCEPT) and not stale,
            "confirmation_receipt": issue_publish_receipt(
                plan, actor, current.snapshot_version, digest, get_settings()) if can_confirm else None,
        }
