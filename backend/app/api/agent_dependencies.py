from typing import Annotated

from fastapi import Depends

from app.agent.agent_service import AgentService
from app.agent.knowledge_tools import SearchKnowledgeBaseTool
from app.agent.langchain_client import LangChainModelClient
from app.agent.read_only_tools import build_read_only_tool_executors
from app.agent.tool_execution import AgentToolExecutorRegistry
from app.agent.tool_registry import AgentToolRegistry
from app.agent.write_tools import build_write_tool_executors
from app.api.dependencies import DbSession
from app.core.config import get_settings
from app.rag.factory import build_rag_service
from app.services.agent_conversation_service import AgentConversationService
from app.services.agent_pending_action_service import AgentPendingActionService
from app.services.delivery_demand_service import DeliveryDemandService
from app.services.dispatch_plan_service import DispatchPlanService
from app.services.vehicle_attendance_service import VehicleAttendanceService
from app.agent.business_task_tools import EXTRA_DEFINITIONS, build_business_task_executors
from app.agent.tool_registry import DEFAULT_TOOL_DEFINITIONS, WRITE_TOOL_DEFINITIONS
from app.agent.tool_execution import AgentToolContext


def build_task_registry(db,*,extended=True):
    registry=AgentToolRegistry((*DEFAULT_TOOL_DEFINITIONS,*WRITE_TOOL_DEFINITIONS,*(EXTRA_DEFINITIONS if extended else ())))
    plans=DispatchPlanService(db)
    executors=AgentToolExecutorRegistry([
        *build_read_only_tool_executors(delivery_demand_service=DeliveryDemandService(db),
            vehicle_attendance_service=VehicleAttendanceService(db),dispatch_plan_service=plans),
        *(build_business_task_executors(db) if extended else []),
        *(build_write_tool_executors(plans) if get_settings().agent_write_tools_enabled else []),
        SearchKnowledgeBaseTool(build_rag_service(db=db) if get_settings().rag_governance_enabled else build_rag_service()),
    ],definition_registry=registry)
    return registry,executors


def get_agent_service(db: DbSession) -> AgentService:
    # Preserve the existing dependency extension point and seven-tool contract.
    # Public HTTP routes wrap this instance in the planned orchestration below.
    tool_registry,executor_registry=build_task_registry(db,extended=False)
    return AgentService(model_client=LangChainModelClient(),tool_registry=tool_registry,
        executor_registry=executor_registry,pending_action_service=AgentPendingActionService(db,executor_registry,
            get_settings().agent_pending_action_expire_minutes))


def get_orchestrated_agent_service(db: DbSession,
    service: Annotated[AgentService,Depends(get_agent_service)]) -> AgentService:
    if not isinstance(service,AgentService):
        return service  # Existing explicit dependency adapters remain supported.
    tool_registry,executor_registry=build_task_registry(db)
    bind=db.get_bind()
    def fresh_read(name,arguments,context):
        import asyncio
        from sqlalchemy.orm import Session
        from app.models.user import User
        from app.domain.exceptions import PermissionDeniedError
        from app.domain.permissions import has_permission
        with Session(bind,autoflush=False) as branch:
            registry,executors=build_task_registry(branch)
            definition=registry.get(name)
            actor=branch.get(User,context.current_user.id)
            if (not definition.read_only or name=='search_knowledge_base' or actor is None or
                    not actor.is_active or not has_permission(actor.role,definition.required_permission)):
                raise PermissionDeniedError()
            return asyncio.run(executors.execute(name,arguments,AgentToolContext(current_user=actor,
                request_id=context.request_id,conversation_id=context.conversation_id)))
    def refresh_actor(user_id):
        from app.models.user import User
        return db.get(User,user_id,populate_existing=True)
    pending_action_service = AgentPendingActionService(
        db,
        executor_registry,
        get_settings().agent_pending_action_expire_minutes,
    )
    service.tool_registry,service.executor_registry=tool_registry,executor_registry
    service.pending_action_service=pending_action_service
    service.orchestration,service.parallel_read,service.refresh_actor=True,fresh_read,refresh_actor
    # A separate connection and JSON-only process boundary for supported reads.
    # In-memory SQLite and RAG clients cannot be reconstructed safely here.
    if bind.dialect.name == 'mysql':
        from app.agent.process_supervisor import run_worker
        async def process_read(name,arguments,context,*,record=None):
            return await run_worker(dict(tool=name,arguments=arguments,
                actor_id=context.current_user.id,conversation_id=context.conversation_id,
                database_url=bind.url.render_as_string(hide_password=False)),
                timeout_seconds=service.tool_timeout_seconds,record=record)
        service.process_read=process_read
    return service


AgentServiceDependency = Annotated[AgentService, Depends(get_orchestrated_agent_service)]


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
        (build_write_tool_executors(dispatch_plan_service)
         if get_settings().agent_write_tools_enabled else []),
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
