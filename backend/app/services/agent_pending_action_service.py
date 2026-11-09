from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.chat_types import AgentPendingActionSnapshot
from app.agent.schemas.tool import AgentToolDefinition
from app.agent.tool_execution import (
    AgentToolContext,
    AgentToolExecutorRegistry,
    AgentToolResult,
)
from app.core.config import get_settings
from app.domain.enums import AgentPendingActionStatus, DispatchPlanStatus
from app.domain.exceptions import (
    AgentPendingActionError,
    BusinessError,
    NotFoundError,
    PermissionDeniedError,
)
from app.domain.permissions import Permission, has_permission
from app.models.agent_pending_action import AgentPendingAction
from app.models.audit_log import AuditLog
from app.models.delivery_demand import DeliveryDemand
from app.models.dispatch_plan import DispatchOrder, DispatchOrderDetail
from app.models.user import User
from app.models.vehicle import Vehicle
from app.repositories.agent_conversation_repository import AgentConversationRepository
from app.repositories.agent_pending_action_repository import (
    AgentPendingActionRepository,
)
from app.services.dispatch_plan_service import DispatchPlanService


class AgentPendingActionService:
    def __init__(
        self,
        session: Session,
        executor_registry: AgentToolExecutorRegistry,
        expire_minutes: int,
    ) -> None:
        self.session = session
        self.executor_registry = executor_registry
        self.expire_minutes = expire_minutes
        self.repository = AgentPendingActionRepository(session)
        self.conversation_repository = AgentConversationRepository(session)
        self.dispatch_plan_service = DispatchPlanService(session)
        self.cancellation_requested = lambda: False
        self.last_write_outcome = None

    def _cancel_before_commit(self, conversation_id, action_id, current_user, *, force=False):
        if not force and not self.cancellation_requested():
            return
        # Roll back business mutations AND the confirmation CAS first. The
        # cancellation receipt is a new, separately committed transaction.
        self.session.rollback()
        self.cancel(conversation_id, action_id, current_user)
        self.session.add(AuditLog(user_id=current_user.id, username=current_user.username,
            action='AGENT_CANCELLED_BEFORE_COMMIT', object_type='AgentPendingAction',
            object_id=action_id, changes={'write_outcome':'CANCELLED_BEFORE_COMMIT'}))
        self.session.commit()
        self.last_write_outcome = 'CANCELLED_BEFORE_COMMIT'
        error = AgentPendingActionError('AGENT_CANCELLED_BEFORE_COMMIT', '提交前已取消，业务写入已回滚')
        error.write_outcome = self.last_write_outcome
        raise error

    @staticmethod
    def require_writes_enabled() -> None:
        if not get_settings().agent_write_tools_enabled:
            raise PermissionDeniedError("Agent当前为只读模式，写操作未启用")

    def create(
        self,
        definition: AgentToolDefinition,
        arguments: BaseModel,
        context: AgentToolContext,
    ) -> AgentPendingAction:
        self.require_writes_enabled()
        if context.conversation_id is None:
            raise AgentPendingActionError(
                "AGENT_CONVERSATION_REQUIRED",
                "Agent写操作必须在持久化会话中发起",
                400,
            )
        if not has_permission(context.current_user.role, definition.required_permission):
            raise PermissionDeniedError("当前用户没有申请该Agent写操作的权限")
        if self.conversation_repository.get_by_id_and_user(
            context.conversation_id, context.current_user.id
        ) is None:
            raise NotFoundError("Agent会话不存在")

        raw_arguments = arguments.model_dump(mode="json")
        summary, display_data, risk_level, risk_message = self._preview(
            definition.name, raw_arguments
        )
        action = AgentPendingAction(
            user_id=context.current_user.id,
            conversation_id=context.conversation_id,
            tool_name=definition.name,
            arguments=raw_arguments,
            summary=summary,
            display_data=display_data,
            risk_level=risk_level,
            risk_message=risk_message,
            status=AgentPendingActionStatus.PENDING,
            expires_at=datetime.now(UTC) + timedelta(minutes=self.expire_minutes),
        )
        return self.repository.add(action)

    def list_owned(self, conversation_id: int, user_id: int) -> list[AgentPendingAction]:
        self._require_conversation(conversation_id, user_id)
        actions = self.repository.list_by_conversation_and_user(conversation_id, user_id)
        changed = False
        for action in actions:
            if self._is_expired(action):
                action.status = AgentPendingActionStatus.EXPIRED
                changed = True
        if changed:
            self.session.commit()
        return actions

    async def confirm(
        self, conversation_id: int, action_id: int, current_user: User
    ) -> tuple[AgentPendingAction, AgentToolResult]:
        self.last_write_outcome = None
        commit_started = False
        self.require_writes_enabled()
        action = self._get_owned(action_id, conversation_id, current_user.id, for_update=True)
        if self._is_expired(action):
            action.status = AgentPendingActionStatus.EXPIRED
            self.session.commit()
            raise AgentPendingActionError("AGENT_ACTION_EXPIRED", "待确认操作已过期")
        self._require_pending(action)
        definition = self.executor_registry.definition_registry.get(action.tool_name)
        if not has_permission(current_user.role, definition.required_permission):
            self.session.rollback()
            raise PermissionDeniedError("当前用户已没有执行该Agent写操作的权限")

        try:
            self._cancel_before_commit(conversation_id, action_id, current_user)
            self._require_unchanged_approval(action)
            if not self.repository.claim_pending(action_id, current_user.id, conversation_id,
                                                 AgentPendingActionStatus.CONFIRMED):
                raise AgentPendingActionError("AGENT_ACTION_NOT_PENDING", "待确认操作已被其他请求处理")
            action.status = AgentPendingActionStatus.CONFIRMED
            action.confirmed_at = datetime.now(UTC)
            self.session.flush()
            result = await self.executor_registry.execute(
                action.tool_name,
                action.arguments,
                AgentToolContext(
                    current_user=current_user,
                    conversation_id=conversation_id,
                    pending_action_id=action.id,
                ),
            )
            action.status = AgentPendingActionStatus.EXECUTED
            action.executed_at = datetime.now(UTC)
            self._cancel_before_commit(conversation_id, action_id, current_user)
            commit_started = True
            self.session.commit()
            self.last_write_outcome = 'COMMITTED'
            self.session.refresh(action)
            return action, result
        except BusinessError as exc:
            if getattr(exc,'write_outcome',None) != 'CANCELLED_BEFORE_COMMIT':
                self._record_write_failure(exc, commit_started, action_id, conversation_id, current_user)
            raise
        except IntegrityError as exc:
            self._record_write_failure(exc, commit_started, action_id, conversation_id, current_user)
            error = AgentPendingActionError("AGENT_ACTION_EXECUTION_CONFLICT", "待确认操作执行冲突")
            error.write_outcome = self.last_write_outcome
            raise error from exc
        except Exception as exc:
            self._record_write_failure(exc, commit_started, action_id, conversation_id, current_user)
            raise
        except BaseException as exc:
            # asyncio cancellation is a BaseException. Never leave a live,
            # partially mutated shared transaction when its coroutine exits.
            self._record_write_failure(exc, commit_started, action_id, conversation_id, current_user)
            raise

    def _record_write_failure(self, original, commit_started, action_id, conversation_id, actor):
        if not commit_started:
            import asyncio
            if isinstance(original,asyncio.CancelledError):
                try:
                    self._cancel_before_commit(conversation_id,action_id,actor,force=True)
                except AgentPendingActionError as stopped:
                    original.write_outcome=getattr(stopped,'write_outcome',None)
                except Exception:
                    self.last_write_outcome='COMPLETION_UNKNOWN'
                    original.write_outcome=self.last_write_outcome
                return
            self._preserve_execution_failure(original, action_id, conversation_id, actor.id)
            return
        self.last_write_outcome = 'COMPLETION_UNKNOWN'
        try:
            self.session.rollback()
            self.recover_execution(conversation_id, action_id, actor)
            self.last_write_outcome = 'COMMITTED'
        except Exception:
            original.add_note('Commit receipt not verified; do not replay the write')
        original.write_outcome = self.last_write_outcome

    def recover_execution(
        self, conversation_id: int, action_id: int, current_user: User
    ) -> AgentToolResult:
        """Read a verified commit receipt after a lost response; never replay a write.

        The legacy confirm endpoint still rejects a second approval. Audit rows
        do not contain the complete historical tool result, so recovery returns
        only the facts established by the committed action and its audit row.
        """
        with self.session.no_autoflush:
            actor = self.session.scalar(select(User).where(User.id == current_user.id)
                                        .execution_options(populate_existing=True))
            if actor is None or not actor.is_active:
                raise PermissionDeniedError()
            action = self.session.scalar(select(AgentPendingAction).where(
                AgentPendingAction.id == action_id,
                AgentPendingAction.user_id == actor.id,
                AgentPendingAction.conversation_id == conversation_id,
            ).execution_options(populate_existing=True))
            if action is None:
                raise NotFoundError("待确认操作不存在")
            self._require_conversation(conversation_id, actor.id)
            # Receipt lookup remains available after the write feature is
            # disabled. It authorizes the same two business tools explicitly;
            # it does not need to expose/re-enable them in the model catalogue.
            if action.tool_name not in {"move_delivery_demand", "cancel_dispatch_plan"}:
                raise AgentPendingActionError("AGENT_ACTION_RECOVERY_UNVERIFIED", "该操作尚不支持结果恢复")
            if not has_permission(actor.role, Permission.DISPATCH_WRITE):
                raise PermissionDeniedError("当前用户已没有查看该Agent写操作执行结果的权限")
            if action.status != AgentPendingActionStatus.EXECUTED:
                raise AgentPendingActionError("AGENT_ACTION_NOT_EXECUTED", "操作尚无已提交的执行结果")
            if action.confirmed_at is None or action.executed_at is None:
                raise AgentPendingActionError("AGENT_ACTION_RECOVERY_UNVERIFIED", "无法核验操作的已提交结果")
            if action.tool_name == "move_delivery_demand":
                audit_action, object_type, object_id = (
                    "DISPATCH_DEMAND_MOVED", "DeliveryDemand", action.arguments.get("delivery_demand_id")
                )
            elif action.tool_name == "cancel_dispatch_plan":
                audit_action, object_type, object_id = (
                    "DISPATCH_PLAN_CANCELLED", "DispatchPlan", action.arguments.get("plan_id")
                )
            audits = self.session.scalars(select(AuditLog).where(
                AuditLog.user_id == actor.id,
                AuditLog.action == audit_action,
                AuditLog.object_type == object_type,
                AuditLog.object_id == object_id,
            )).all()
            matching = [row for row in audits if isinstance(row.changes, dict)
                        and row.changes.get("source") == "agent"
                        and row.changes.get("tool_name") == action.tool_name
                        and type(row.changes.get("pending_action_id")) is int
                        and row.changes["pending_action_id"] == action.id]
            if len(matching) != 1:
                raise AgentPendingActionError("AGENT_ACTION_RECOVERY_UNVERIFIED", "操作审计缺失或冲突，需人工核验")
            audit = matching[0]
            if action.tool_name == "move_delivery_demand" and any(
                audit.changes.get(key) != action.arguments.get(key)
                for key in ("plan_id", "source_order_id", "target_order_id")
            ):
                raise AgentPendingActionError("AGENT_ACTION_RECOVERY_UNVERIFIED", "操作审计与审批对象不一致")
            return AgentToolResult.from_data(action.tool_name, {
                "status": "executed", "recovery_verified": True,
                "action_id": action.id, "tool_name": action.tool_name,
                "plan_id": action.arguments["plan_id"], "audit_id": audit.id,
                "result_reconstructed": "commit_receipt_only",
                "original_result_available": False,
            })

    def _require_unchanged_approval(self, action: AgentPendingAction) -> None:
        """Lock the approved object and reject a stale approval before its CAS.

        The stored display is the consent snapshot, not a mutable preview. The
        original business validators still run after this independent check.
        """
        # Legacy graph state is resumable, but a legacy approval without a
        # business snapshot must be re-created rather than silently trusted.
        fingerprint = action.display_data.get("approval_fingerprint")
        if not isinstance(fingerprint, str) or len(fingerprint) != 64:
            raise AgentPendingActionError("AGENT_ACTION_SNAPSHOT_CHANGED", "旧审批缺少业务快照，请重新申请确认")
        plan_id = action.arguments.get("plan_id")
        if type(plan_id) is not int:
            raise AgentPendingActionError("AGENT_ACTION_SNAPSHOT_CHANGED", "审批内容已变化，请重新申请确认")
        plan = self.dispatch_plan_service.repository.get_for_update(plan_id)
        if plan is None:
            raise AgentPendingActionError("AGENT_ACTION_SNAPSHOT_CHANGED", "审批对象已变化，请重新申请确认")
        # Relationships are loaded with separate SELECTs by the repository;
        # lock their rows explicitly rather than assuming the plan lock covers
        # them. SQLite ignores these locks; MySQL verification is separate.
        self.session.scalars(select(DispatchOrder).where(DispatchOrder.plan_id == plan_id)
                             .order_by(DispatchOrder.id).with_for_update()
                             .execution_options(populate_existing=True)).all()
        self.session.scalars(select(DispatchOrderDetail).join(DispatchOrder).where(
            DispatchOrder.plan_id == plan_id
        ).order_by(DispatchOrderDetail.id).with_for_update()
          .execution_options(populate_existing=True)).all()
        try:
            summary, display, risk_level, risk_message = self._preview(
                action.tool_name, action.arguments, lock_snapshot=True
            )
        except BusinessError as exc:
            raise AgentPendingActionError(
                "AGENT_ACTION_SNAPSHOT_CHANGED", "审批对象已变化，请重新申请确认"
            ) from exc
        if (action.summary != summary or action.display_data != display
                or action.risk_level != risk_level or action.risk_message != risk_message):
            raise AgentPendingActionError("AGENT_ACTION_SNAPSHOT_CHANGED", "审批内容已变化，请重新申请确认")

    def _preserve_execution_failure(
        self, original: Exception, action_id: int, conversation_id: int, user_id: int
    ) -> None:
        """Best-effort bookkeeping cannot replace the original failure.

        A database disconnect can also break rollback or the failure record.
        Keep that uncertainty explicit on the original exception; never retry
        the side effect or assume that a failed commit response means no commit.
        """
        try:
            self.session.rollback()
        except Exception as secondary:
            original.add_note(f"Agent rollback not verified: {type(secondary).__name__}")
            return
        try:
            self._mark_failed(action_id, conversation_id, user_id)
        except Exception as secondary:
            original.add_note(f"Agent failure state not persisted: {type(secondary).__name__}")

    def cancel(self, conversation_id: int, action_id: int, current_user: User) -> AgentPendingAction:
        action = self._get_owned(action_id, conversation_id, current_user.id, for_update=True)
        if self._is_expired(action):
            action.status = AgentPendingActionStatus.EXPIRED
            self.session.commit()
            raise AgentPendingActionError("AGENT_ACTION_EXPIRED", "待确认操作已过期")
        self._require_pending(action)
        if not self.repository.claim_pending(action_id, current_user.id, conversation_id,
                                             AgentPendingActionStatus.CANCELLED):
            self.session.rollback()
            raise AgentPendingActionError("AGENT_ACTION_NOT_PENDING", "待确认操作已被其他请求处理")
        action.status = AgentPendingActionStatus.CANCELLED
        self.session.commit()
        self.session.refresh(action)
        return action

    @staticmethod
    def snapshot(action: AgentPendingAction) -> AgentPendingActionSnapshot:
        return AgentPendingActionSnapshot.model_validate(action)

    def _approval_fingerprint(self, plan, *, lock: bool) -> str:
        """Hash only business identity/state, never contact data or free text.

        A member replacement can preserve both plan version and item count.
        Bind consent to the complete member/quantity/assignment snapshot too.
        Changes outside this snapshot still face the original final validators.
        """
        vehicle_ids = sorted({order.vehicle.id for order in plan.orders})
        vehicles_query = select(Vehicle).where(Vehicle.id.in_(vehicle_ids)).order_by(Vehicle.id)
        if lock:
            vehicles_query = vehicles_query.with_for_update()
        vehicles = self.session.scalars(vehicles_query.execution_options(populate_existing=True)).all()
        driver_ids = sorted({value for value in (
            *[order.actual_driver_id for order in plan.orders],
            *[vehicle.driver_user_id for vehicle in vehicles],
        ) if value is not None})
        drivers_query = select(User).where(User.id.in_(driver_ids)).order_by(User.id)
        if lock:
            drivers_query = drivers_query.with_for_update()
        drivers = self.session.scalars(drivers_query.execution_options(populate_existing=True)).all()
        demand_ids = sorted({detail.delivery_demand_id for order in plan.orders for detail in order.details}
                            | {item.delivery_demand_id for item in plan.unassigned_demands})
        demands_query = select(DeliveryDemand).where(DeliveryDemand.id.in_(demand_ids)).order_by(DeliveryDemand.id)
        if lock:
            demands_query = demands_query.with_for_update()
        demands = self.session.scalars(demands_query.execution_options(populate_existing=True)).all()
        payload = {
            "schema": 1,
            "plan": {"id": plan.id, "date": plan.delivery_date.isoformat(),
                     "version": plan.version, "status": plan.status.value},
            "orders": [{"id": order.id, "vehicle_id": order.vehicle.id,
                        "driver_id": order.actual_driver_id, "route_id": order.route.id,
                        "period": order.period.value, "trip_no": order.trip_no,
                        "total_load": str(order.total_load),
                        "details": [{"id": detail.id, "demand_id": detail.delivery_demand_id,
                                     "quantity": str(detail.quantity), "status": detail.status.value,
                                     "delivery_status": detail.delivery_status.value}
                                    for detail in sorted(order.details, key=lambda value: value.id)]}
                       for order in sorted(plan.orders, key=lambda value: value.id)],
            "unassigned": [{"id": item.id, "demand_id": item.delivery_demand_id,
                            "quantity": str(item.quantity), "period": item.period.value}
                           for item in sorted(plan.unassigned_demands, key=lambda value: value.id)],
            "vehicles": [{"id": vehicle.id, "type_id": vehicle.vehicle_type_id,
                          "driver_id": vehicle.driver_user_id, "is_active": vehicle.is_active,
                          "operating_status": vehicle.operating_status,
                          "rated_load": str(vehicle.rated_load) if vehicle.rated_load is not None else None,
                          "daily_trip_limit": vehicle.daily_trip_limit,
                          "allowed_routes": sorted(vehicle.allowed_route_ids) if vehicle.allowed_route_ids is not None else None}
                         for vehicle in vehicles],
            "drivers": [{"id": driver.id, "is_active": driver.is_active, "role": driver.role.value}
                        for driver in drivers],
            "demands": [{"id": demand.id, "date": demand.date.isoformat(), "store_id": demand.store_id,
                         "period": demand.period.value, "quantity": str(demand.quantity),
                         "status": demand.status.value, "priority": demand.priority.value}
                        for demand in demands],
        }
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")).encode("utf-8")).hexdigest()

    def _preview(self, tool_name: str, arguments: dict[str, Any], *, lock_snapshot: bool = False) -> tuple[str, dict[str, Any], str, str]:
        plan = self.dispatch_plan_service.get(int(arguments["plan_id"]))
        if tool_name == "move_delivery_demand":
            if plan.status != DispatchPlanStatus.DRAFT:
                raise AgentPendingActionError("PLAN_NOT_DRAFT", "只有DRAFT方案可以人工调整")
            source = next((item for item in plan.orders if item.id == arguments["source_order_id"]), None)
            target = next((item for item in plan.orders if item.id == arguments["target_order_id"]), None)
            if source is None or target is None:
                raise AgentPendingActionError("ORDER_NOT_IN_PLAN", "原任务或目标任务不属于当前方案")
            detail = next((item for item in source.details if item.delivery_demand_id == arguments["delivery_demand_id"]), None)
            if detail is None:
                raise AgentPendingActionError("DEMAND_NOT_IN_SOURCE", "配送需求不属于指定原任务")
            display = {
                "plan_id": plan.id,
                "plan_version": plan.version,
                "delivery_demand_id": detail.delivery_demand_id,
                "quantity": str(detail.quantity),
                "source_order_id": source.id,
                "source_vehicle": source.vehicle.plate_number,
                "target_order_id": target.id,
                "target_vehicle": target.vehicle.plate_number,
                "approval_fingerprint": self._approval_fingerprint(plan, lock=lock_snapshot),
            }
            return (
                f"将配送需求 #{detail.delivery_demand_id} 从任务 #{source.id} 移动到任务 #{target.id}",
                display,
                "MEDIUM",
                "确认后将重新执行地形、线路、时段和载重规则校验。",
            )
        if tool_name == "cancel_dispatch_plan":
            if plan.status not in {DispatchPlanStatus.DRAFT, DispatchPlanStatus.PUBLISHED}:
                raise AgentPendingActionError("PLAN_NOT_CANCELLABLE", "当前方案状态不能取消")
            display = {
                "plan_id": plan.id,
                "delivery_date": plan.delivery_date.isoformat(),
                "version": plan.version,
                "current_status": plan.status.value,
                "assigned_demand_count": sum(len(order.details) for order in plan.orders),
                "approval_fingerprint": self._approval_fingerprint(plan, lock=lock_snapshot),
            }
            return (
                f"取消 {plan.delivery_date.isoformat()} V{plan.version} 派车方案",
                display,
                "HIGH",
                "取消会释放或回退方案关联需求状态；确认前请核对方案版本与当前状态。",
            )
        raise AgentPendingActionError("AGENT_WRITE_TOOL_UNSUPPORTED", "该写操作暂不支持确认执行", 400)

    def _require_conversation(self, conversation_id: int, user_id: int) -> None:
        if self.conversation_repository.get_by_id_and_user(conversation_id, user_id) is None:
            raise NotFoundError("Agent会话不存在")

    def _get_owned(self, action_id: int, conversation_id: int, user_id: int, *, for_update: bool) -> AgentPendingAction:
        action = self.repository.get_owned(action_id, conversation_id, user_id, for_update=for_update)
        if action is None:
            raise NotFoundError("待确认操作不存在")
        return action

    def _mark_failed(self, action_id: int, conversation_id: int, user_id: int) -> None:
        """Persist execution failure only after the business transaction has rolled back."""
        failed = self._get_owned(action_id, conversation_id, user_id, for_update=True)
        if failed.status == AgentPendingActionStatus.PENDING:
            failed.status = AgentPendingActionStatus.FAILED
            self.session.commit()

    @staticmethod
    def _is_expired(action: AgentPendingAction) -> bool:
        if action.status != AgentPendingActionStatus.PENDING:
            return False
        expires_at = action.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at <= datetime.now(UTC)

    @staticmethod
    def _require_pending(action: AgentPendingAction) -> None:
        if action.status == AgentPendingActionStatus.EXECUTED:
            raise AgentPendingActionError("AGENT_ACTION_ALREADY_EXECUTED", "待确认操作已执行，不能重复执行")
        if action.status != AgentPendingActionStatus.PENDING:
            raise AgentPendingActionError("AGENT_ACTION_NOT_PENDING", f"当前操作状态为{action.status.value}，不能执行")
