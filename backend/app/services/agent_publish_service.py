"""Human-confirmed publication of one Agent draft in a serializable transaction."""
import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.domain.enums import DispatchPlanStatus, UserRole
from app.domain.exceptions import BusinessError, ConflictError, NotFoundError, PermissionDeniedError
from app.models.agent_dispatch_acceptance import AgentDispatchOperation, AgentDispatchPlanSource, DispatchDateGuard
from app.models.user import User
from app.repositories.dispatch_plan_repository import DispatchPlanRepository
from app.services.agent_publish_preview_service import persisted_plan_digest
from app.services.agent_publish_receipt import verify_publish_receipt
from app.services.audit_log_service import AuditAction, AuditLogService
from app.services.dispatch_context_service import DispatchContextService
from app.services.dispatch_plan_service import DispatchPlanService
from app.services.driver_leave_service import DriverLeaveService


class AgentPublishService:
    def __init__(self, engine, settings):
        self.engine = engine
        self.settings = settings

    def confirm(self, plan_id: int, receipt: str, idempotency_key: str,
                confirmed: bool, actor_id: int):
        if not self.settings.agent_plan_publish_enabled or not (self.settings.agent_plan_publish_admin_enabled or self.settings.agent_plan_publish_dispatcher_enabled):
            raise PermissionDeniedError("Agent 人工发布功能未启用")
        if self.engine.dialect.name != "mysql":
            raise BusinessError("Agent 人工发布需要专用 MySQL 事务环境", 503, "MYSQL_REQUIRED")
        if not confirmed:
            raise BusinessError("请先明确确认正式发布", 400, "CONFIRMATION_REQUIRED")
        if not (8 <= len(idempotency_key) <= 100 and idempotency_key.isascii() and
                all(c.isalnum() or c in "-_" for c in idempotency_key)):
            raise BusinessError("幂等键格式无效", 400, "INVALID_IDEMPOTENCY_KEY")
        request_digest = hashlib.sha256(f"{plan_id}:{receipt}".encode()).hexdigest()
        serial_engine = self.engine.execution_options(isolation_level="SERIALIZABLE")
        try:
            with Session(serial_engine, autoflush=False, expire_on_commit=False) as tx:
                with tx.begin():
                    actor = tx.get(User, actor_id, with_for_update=True)
                    if actor is None or not actor.is_active or not ((actor.role == UserRole.ADMIN and self.settings.agent_plan_publish_admin_enabled) or
                        (actor.role == UserRole.DISPATCHER and self.settings.agent_plan_publish_dispatcher_enabled)):
                        raise PermissionDeniedError()
                    operation = tx.scalar(select(AgentDispatchOperation).where(
                        AgentDispatchOperation.actor_id == actor_id,
                        AgentDispatchOperation.operation == "CONFIRM_PUBLISH",
                        AgentDispatchOperation.idempotency_key == idempotency_key).with_for_update())
                    if operation is not None:
                        if operation.request_sha256 != request_digest or operation.plan_id != plan_id:
                            raise ConflictError("幂等键已用于另一发布请求")
                        existing = DispatchPlanRepository(tx).get(operation.plan_id)
                        if existing is None:
                            raise NotFoundError("派车方案不存在")
                        return DispatchPlanService(tx)._to_detail(existing)

                    DriverLeaveService(tx).lock_resources()
                    plan = DispatchPlanRepository(tx).get_for_update(plan_id)
                    if plan is None or tx.get(AgentDispatchPlanSource, plan_id) is None:
                        raise NotFoundError("Agent 草稿不存在")
                    if plan.status != DispatchPlanStatus.DRAFT:
                        raise ConflictError("方案已经发布或不再是草稿")
                    guard = tx.scalar(select(DispatchDateGuard).where(
                        DispatchDateGuard.delivery_date == plan.delivery_date).with_for_update())
                    if guard is None:
                        raise ConflictError("方案日期保护记录缺失")
                    source = tx.get(AgentDispatchPlanSource, plan_id)
                    current = DispatchContextService(tx).load(plan.delivery_date)
                    if current.snapshot_version != source.post_save_snapshot_version:
                        raise BusinessError("草稿保存后的业务数据已变化，请重新规划", 409, "STALE_AGENT_DRAFT")
                    digest = persisted_plan_digest(plan)
                    proof = verify_publish_receipt(receipt, plan, actor,
                                                   current.snapshot_version, digest, self.settings)
                    nonce_hash = hashlib.sha256(proof["nonce"].encode()).hexdigest()
                    if tx.scalar(select(AgentDispatchOperation.id).where(
                            AgentDispatchOperation.receipt_nonce_hash == nonce_hash)) is not None:
                        raise ConflictError("发布确认凭据已使用")
                    result = DispatchPlanService(tx).publish(plan_id, actor,
                                                             agent_authorized=True, commit=False)
                    tx.add(AgentDispatchOperation(
                        actor_id=actor_id, operation="CONFIRM_PUBLISH", idempotency_key=idempotency_key,
                        request_sha256=request_digest, receipt_nonce_hash=nonce_hash,
                        plan_id=plan_id, created_at=datetime.now(UTC)))
                    AuditLogService(tx).add(actor, AuditAction.AGENT_PLAN_CONFIRMED_PUBLISHED,
                                            "DispatchPlan", plan_id,
                                            {"plan_sha256": digest,
                                             "snapshot_version": current.snapshot_version,
                                             "version": plan.version})
                    tx.flush()
                    response = result
            return response
        except IntegrityError as exc:
            raise ConflictError("发布确认发生并发冲突，请刷新后重试") from exc
        except DBAPIError as exc:
            if getattr(exc.orig, "args", [None])[0] in (1205, 1213):
                raise ConflictError("派车资源正在被其他操作修改，请刷新后重试") from exc
            raise
