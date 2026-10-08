from typing import Annotated

from fastapi import Depends

from app.agent.agent_service import AgentService
from app.agent.model_client import OpenAICompatibleModelClient
from app.agent.knowledge_tools import SearchKnowledgeBaseTool
from app.agent.read_only_tools import build_read_only_tool_executors
from app.agent.tool_execution import AgentToolExecutorRegistry
from app.agent.write_tools import build_write_tool_executors
from app.agent.tool_registry import AgentToolRegistry
from app.api.dependencies import DbSession
from app.core.config import get_settings
from app.services.agent_conversation_service import AgentConversationService
from app.services.delivery_demand_service import DeliveryDemandService
from app.services.dispatch_plan_service import DispatchPlanService
from app.services.vehicle_attendance_service import VehicleAttendanceService
from app.services.agent_pending_action_service import AgentPendingActionService
from app.rag.factory import build_rag_service


def get_agent_service(db: DbSession) -> AgentService:
    tool_registry = AgentToolRegistry()
    dispatch_plan_service = DispatchPlanService(db)
    executor_registry = AgentToolExecutorRegistry(
        [
            *build_read_only_tool_executors(
        delivery_demand_service=DeliveryDemandService(db),
        vehicle_attendance_service=VehicleAttendanceService(db),
                dispatch_plan_service=dispatch_plan_service,
            ),
            *build_write_tool_executors(dispatch_plan_service),
            SearchKnowledgeBaseTool(build_rag_service()),
        ],
        definition_registry=tool_registry,
    )
    pending_action_service = AgentPendingActionService(
        db,
        executor_registry,
        get_settings().agent_pending_action_expire_minutes,
    )
    return AgentService(
        model_client=OpenAICompatibleModelClient(),
        tool_registry=tool_registry,
        executor_registry=executor_registry,
        pending_action_service=pending_action_service,
    )


AgentServiceDependency = Annotated[AgentService, Depends(get_agent_service)]


def get_agent_conversation_service(
    db: DbSession,
) -> AgentConversationService:
    return AgentConversationService(
        db,
        history_max_messages=get_settings().agent_history_max_messages,
    )


AgentConversationServiceDependency = Annotated[
    AgentConversationService,
    Depends(get_agent_conversation_service),
]


def get_agent_pending_action_service(db: DbSession) -> AgentPendingActionService:
    tool_registry = AgentToolRegistry()
    dispatch_plan_service = DispatchPlanService(db)
    executor_registry = AgentToolExecutorRegistry(
        build_write_tool_executors(dispatch_plan_service),
        definition_registry=tool_registry,
    )
    return AgentPendingActionService(
        db,
        executor_registry,
        get_settings().agent_pending_action_expire_minutes,
    )


AgentPendingActionServiceDependency = Annotated[
    AgentPendingActionService,
    Depends(get_agent_pending_action_service),
]
