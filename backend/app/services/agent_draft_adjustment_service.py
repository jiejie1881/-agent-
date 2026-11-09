"""Explicit manual adjustment of Agent drafts with optimistic and database locks."""
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from app.domain.enums import UserRole, DispatchPlanStatus
from app.domain.exceptions import BusinessError, PermissionDeniedError, NotFoundError, DispatchPlanValidationError
from app.models.user import User
from app.models.agent_dispatch_acceptance import AgentDispatchPlanSource, DispatchDateGuard
from app.repositories.dispatch_plan_repository import DispatchPlanRepository
from app.services.driver_leave_service import DriverLeaveService
from app.services.dispatch_context_service import DispatchContextService
from app.services.agent_publish_preview_service import persisted_plan_digest
from app.services.dispatch_plan_service import DispatchPlanService
from app.services.audit_log_service import AuditLogService
from app.core.config import get_settings
from app.domain.permissions import Permission, has_permission

class AgentDraftAdjustmentService:
    def __init__(self, engine):
        self.engine = engine

    def move(self, plan_id, data, expected_plan_sha256, actor_id):
        if self.engine.dialect.name != 'mysql':
            raise BusinessError('Agent 草稿调整需要 MySQL 事务环境',503,'MYSQL_REQUIRED')
        try:
            with Session(self.engine.execution_options(isolation_level='SERIALIZABLE'), autoflush=False, expire_on_commit=False) as tx:
                with tx.begin():
                    actor=tx.get(User,actor_id,with_for_update=True)
                    if actor is None or not actor.is_active or not get_settings().agent_draft_accept_enabled or not has_permission(actor.role,Permission.AGENT_DRAFT_ACCEPT):
                        raise PermissionDeniedError()
                    DriverLeaveService(tx).lock_resources()
                    plan=DispatchPlanRepository(tx).get_for_update(plan_id)
                    source=tx.get(AgentDispatchPlanSource,plan_id)
                    if plan is None or source is None:
                        raise NotFoundError('Agent 草稿不存在')
                    if plan.status != DispatchPlanStatus.DRAFT:
                        raise BusinessError('只有 Agent 草稿允许人工调整',409,'PLAN_NOT_DRAFT')
                    tx.scalar(select(DispatchDateGuard).where(DispatchDateGuard.delivery_date==plan.delivery_date).with_for_update())
                    before=persisted_plan_digest(plan)
                    if expected_plan_sha256 != before:
                        raise BusinessError('草稿内容已变化，请刷新后重新确认',409,'STALE_AGENT_PLAN')
                    current=DispatchContextService(tx).load(plan.delivery_date)
                    if current.snapshot_version != source.post_save_snapshot_version:
                        raise BusinessError('保存后的业务资料已变化，请重新规划',409,'STALE_AGENT_DRAFT')
                    service=DispatchPlanService(tx)
                    service.move_demand(plan_id,data,actor,commit=False,agent_authorized=True,
                        audit_context={'source':'AGENT','plan_sha256_before':before})
                    tx.flush()
                    issues=service.publication_validator.validate(plan)
                    if issues:
                        raise DispatchPlanValidationError(issues)
                    source.post_save_snapshot_version=DispatchContextService(tx).load(plan.delivery_date).snapshot_version
                    after=persisted_plan_digest(plan)
                    AuditLogService(tx).add(actor,'AGENT_DRAFT_MANUALLY_ADJUSTED','DispatchPlan',plan_id,
                        {'plan_sha256_before':before,'plan_sha256_after':after,'snapshot_version':source.post_save_snapshot_version})
                    result=service._to_detail(plan)
            return result
        except DBAPIError as exc:
            if getattr(exc.orig,'args',[None])[0] in (1205,1213):
                raise BusinessError('派车资源正在修改，请刷新后重试',409,'CONCURRENT_MODIFICATION') from exc
            raise
