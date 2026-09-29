from typing import Annotated

from fastapi import Depends

from app.agent.agent_service import AgentService
from app.agent.model_client import OpenAICompatibleModelClient
from app.agent.read_only_tools import build_read_only_tool_executor_registry
from app.agent.tool_registry import AgentToolRegistry
from app.api.dependencies import DbSession
from app.core.config import get_settings
from app.services.agent_conversation_service import AgentConversationService
from app.services.delivery_demand_service import DeliveryDemandService
from app.services.dispatch_plan_service import DispatchPlanService
from app.services.vehicle_attendance_service import VehicleAttendanceService


def get_agent_service(db: DbSession) -> AgentService:
    tool_registry = AgentToolRegistry()
    executor_registry = build_read_only_tool_executor_registry(
        delivery_demand_service=DeliveryDemandService(db),
        vehicle_attendance_service=VehicleAttendanceService(db),
        dispatch_plan_service=DispatchPlanService(db),
        definition_registry=tool_registry,
    )
    return AgentService(
        model_client=OpenAICompatibleModelClient(),
        tool_registry=tool_registry,
        executor_registry=executor_registry,
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
