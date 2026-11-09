from typing import Any

from app.agent.schemas.tool import CancelDispatchPlanArgs, MoveDeliveryDemandArgs
from app.agent.tool_execution import (
    AgentToolContext,
    AgentToolExecutor,
    AgentToolExecutorRegistry,
)
from app.agent.tool_registry import AgentToolRegistry
from app.core.config import get_settings
from app.domain.enums import AgentPendingActionStatus, DispatchPlanStatus
from app.domain.exceptions import ConflictError, PermissionDeniedError
from app.domain.permissions import Permission, has_permission
from app.models.agent_pending_action import AgentPendingAction
from app.models.user import User
from app.schemas.dispatch_plan import DispatchDemandMoveRequest
from app.services.dispatch_plan_service import DispatchPlanService


def _authorize_write(service, context, name, arguments):
    if not get_settings().agent_write_tools_enabled:
        raise PermissionDeniedError("Agent当前为只读模式，写操作未启用")
    actor = service.session.get(User, context.current_user.id, populate_existing=True)
    if actor is None or not actor.is_active or not has_permission(actor.role, Permission.DISPATCH_WRITE):
        raise PermissionDeniedError()
    action = (service.session.get(AgentPendingAction, context.pending_action_id)
              if context.pending_action_id is not None else None)
    if (action is None or action.status != AgentPendingActionStatus.CONFIRMED
            or action.user_id != actor.id or action.conversation_id != context.conversation_id
            or action.tool_name != name or action.arguments != arguments.model_dump(mode="json")):
        raise PermissionDeniedError("Agent写操作必须经过所属用户的人工确认")


def _audit_context(context: AgentToolContext, tool_name: str) -> dict[str, object]:
    return {
        "source": "agent",
        "tool_name": tool_name,
        "pending_action_id": context.pending_action_id,
        "result": "success",
    }


class MoveDeliveryDemandTool(AgentToolExecutor[MoveDeliveryDemandArgs]):
    name = "move_delivery_demand"
    arguments_type = MoveDeliveryDemandArgs
    preserve_business_errors = True

    def __init__(self, service: DispatchPlanService) -> None:
        self.service = service

    def _execute(self, arguments: MoveDeliveryDemandArgs, context: AgentToolContext) -> dict[str, Any]:
        _authorize_write(self.service, context, self.name, arguments)
        plan = self.service.move_demand(
            arguments.plan_id,
            DispatchDemandMoveRequest(
                delivery_demand_id=arguments.delivery_demand_id,
                source_order_id=arguments.source_order_id,
                target_order_id=arguments.target_order_id,
            ),
            context.current_user,
            commit=False,
            audit_context=_audit_context(context, self.name),
        )
        return {"status": "executed", "plan_id": plan.id, "version": plan.version}


class CancelDispatchPlanTool(AgentToolExecutor[CancelDispatchPlanArgs]):
    name = "cancel_dispatch_plan"
    arguments_type = CancelDispatchPlanArgs
    preserve_business_errors = True

    def __init__(self, service: DispatchPlanService) -> None:
        self.service = service

    def _execute(self, arguments: CancelDispatchPlanArgs, context: AgentToolContext) -> dict[str, Any]:
        _authorize_write(self.service, context, self.name, arguments)
        current = self.service.get(arguments.plan_id)
        if current.status == DispatchPlanStatus.CANCELLED:
            raise ConflictError("派车方案已经取消，待确认操作已失效")
        plan = self.service.cancel(
            arguments.plan_id,
            context.current_user,
            commit=False,
            audit_context=_audit_context(context, self.name),
        )
        return {"status": "executed", "plan_id": plan.id, "plan_status": plan.status.value}


def build_write_tool_executors(service: DispatchPlanService) -> list[AgentToolExecutor[Any]]:
    return [MoveDeliveryDemandTool(service), CancelDispatchPlanTool(service)]


def build_write_tool_executor_registry(
    service: DispatchPlanService, definition_registry: AgentToolRegistry
) -> AgentToolExecutorRegistry:
    return AgentToolExecutorRegistry(build_write_tool_executors(service), definition_registry)
