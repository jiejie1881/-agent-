from typing import Any

from app.agent.schemas.tool import CancelDispatchPlanArgs, MoveDeliveryDemandArgs
from app.agent.tool_execution import AgentToolContext, AgentToolExecutor, AgentToolExecutorRegistry
from app.agent.tool_registry import AgentToolRegistry
from app.schemas.dispatch_plan import DispatchDemandMoveRequest
from app.domain.enums import DispatchPlanStatus
from app.domain.exceptions import ConflictError
from app.services.dispatch_plan_service import DispatchPlanService


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
