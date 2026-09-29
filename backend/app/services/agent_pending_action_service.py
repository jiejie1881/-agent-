from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.chat_types import AgentPendingActionSnapshot
from app.agent.schemas.tool import AgentToolDefinition
from app.agent.tool_execution import AgentToolContext, AgentToolExecutorRegistry, AgentToolResult
from app.domain.enums import AgentPendingActionStatus, DispatchPlanStatus
from app.domain.exceptions import AgentPendingActionError, BusinessError, NotFoundError, PermissionDeniedError
from app.domain.permissions import has_permission
from app.models.agent_pending_action import AgentPendingAction
from app.models.user import User
from app.repositories.agent_conversation_repository import AgentConversationRepository
from app.repositories.agent_pending_action_repository import AgentPendingActionRepository
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

    def create(
        self,
        definition: AgentToolDefinition,
        arguments: BaseModel,
        context: AgentToolContext,
    ) -> AgentPendingAction:
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
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=self.expire_minutes),
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
            action.status = AgentPendingActionStatus.CONFIRMED
            action.confirmed_at = datetime.now(timezone.utc)
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
            action.executed_at = datetime.now(timezone.utc)
            self.session.commit()
            self.session.refresh(action)
            return action, result
        except BusinessError:
            self.session.rollback()
            failed = self._get_owned(action_id, conversation_id, current_user.id, for_update=True)
            if failed.status == AgentPendingActionStatus.PENDING:
                failed.status = AgentPendingActionStatus.FAILED
                self.session.commit()
            raise
        except IntegrityError as exc:
            self.session.rollback()
            raise AgentPendingActionError("AGENT_ACTION_EXECUTION_CONFLICT", "待确认操作执行冲突") from exc

    def cancel(self, conversation_id: int, action_id: int, current_user: User) -> AgentPendingAction:
        action = self._get_owned(action_id, conversation_id, current_user.id, for_update=True)
        if self._is_expired(action):
            action.status = AgentPendingActionStatus.EXPIRED
            self.session.commit()
            raise AgentPendingActionError("AGENT_ACTION_EXPIRED", "待确认操作已过期")
        self._require_pending(action)
        action.status = AgentPendingActionStatus.CANCELLED
        self.session.commit()
        self.session.refresh(action)
        return action

    @staticmethod
    def snapshot(action: AgentPendingAction) -> AgentPendingActionSnapshot:
        return AgentPendingActionSnapshot.model_validate(action)

    def _preview(self, tool_name: str, arguments: dict[str, Any]) -> tuple[str, dict[str, Any], str, str]:
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

    @staticmethod
    def _is_expired(action: AgentPendingAction) -> bool:
        if action.status != AgentPendingActionStatus.PENDING:
            return False
        expires_at = action.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= datetime.now(timezone.utc)

    @staticmethod
    def _require_pending(action: AgentPendingAction) -> None:
        if action.status == AgentPendingActionStatus.EXECUTED:
            raise AgentPendingActionError("AGENT_ACTION_ALREADY_EXECUTED", "待确认操作已执行，不能重复执行")
        if action.status != AgentPendingActionStatus.PENDING:
            raise AgentPendingActionError("AGENT_ACTION_NOT_PENDING", f"当前操作状态为{action.status.value}，不能执行")
