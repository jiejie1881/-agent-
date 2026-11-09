from __future__ import annotations

from collections.abc import Sequence

from app.agent.chat_types import AgentChatResult
from app.agent.graph_store import AgentGraphStore
from app.agent.graph_workflow import AgentWorkflow
from app.agent.model_client import AgentModelClient
from app.agent.model_types import AgentMessageRole, AgentModelMessage
from app.agent.prompts.system_prompt import AGENT_SYSTEM_PROMPT
from app.agent.tool_execution import AgentToolContext, AgentToolExecutorRegistry
from app.agent.tool_registry import AgentToolRegistry
from app.core.config import get_settings
from app.services.agent_pending_action_service import AgentPendingActionService


class AgentService:
    """Stable business facade; StateGraph is the only orchestration loop."""

    def __init__(self, model_client: AgentModelClient, tool_registry: AgentToolRegistry,
                 executor_registry: AgentToolExecutorRegistry, *,
                 max_tool_calls: int | None = None,
                 system_prompt: str = AGENT_SYSTEM_PROMPT,
                 pending_action_service: AgentPendingActionService | None = None,
                 checkpoint_path=None, orchestration=False, parallel_read=None,
                 refresh_actor=None, max_replans=1, tool_timeout_seconds=30.0, retry_policy=None,
                 execution_deadline_seconds=120.0, process_read=None, answer_contract=None) -> None:
        if answer_contract is not None:
            from app.rag.answer_contract import IsolatedAnswerContract
            from app.rag.semantic_contract import IsolatedSemanticContract
            if type(answer_contract) not in (IsolatedAnswerContract, IsolatedSemanticContract):
                raise TypeError('Explicit isolated answer contract required')
            answer_contract.validate_installation(checkpoint_path)
        self.answer_contract = answer_contract
        limit = get_settings().agent_max_tool_calls if max_tool_calls is None else max_tool_calls
        if limit < 1:
            raise ValueError('max_tool_calls must be at least 1')
        self.model_client = model_client
        self.tool_registry = tool_registry
        self.executor_registry = executor_registry
        self.max_tool_calls = limit
        self.system_prompt = system_prompt
        self.pending_action_service = pending_action_service
        self.graph_store = AgentGraphStore(checkpoint_path)
        if type(max_replans) is not int or not 0 <= max_replans <= 2:
            raise ValueError('max_replans must be in [0, 2]')
        self.orchestration,self.parallel_read,self.refresh_actor,self.max_replans = orchestration,parallel_read,refresh_actor,max_replans
        if not 0 < tool_timeout_seconds <= 120:raise ValueError('tool timeout must be in (0,120]')
        self.tool_timeout_seconds,self.retry_policy=tool_timeout_seconds,retry_policy
        from app.agent.execution_control import ExecutionControl
        ExecutionControl(execution_deadline_seconds)
        self.execution_deadline_seconds=execution_deadline_seconds
        self.process_read=process_read

    def workflow(self,context):
        if self.orchestration:
            from app.agent.task_workflow import TaskWorkflow
            return TaskWorkflow(self,context,self.graph_store)
        return AgentWorkflow(self,context,self.graph_store)

    async def chat(self, user_message: str, context: AgentToolContext,
                   history: Sequence[AgentModelMessage] = ()) -> AgentChatResult:
        self._validate_history(history)
        if get_settings().agent_memory_enabled:
            import asyncio
            import json
            import logging
            from dataclasses import replace
            def recall():
                from app.infrastructure.database.session import SessionLocal
                from app.services.agent_memory_service import memory_service
                with SessionLocal() as db:
                    return memory_service(db).search(context.current_user.id, user_message)
            try:
                memories = await asyncio.to_thread(recall)
                from app.agent.stream_events import emit
                emit('memory_retrieval', {'count': len(memories)})
                context = replace(context, memory_context=json.dumps(memories, ensure_ascii=False))
            except Exception:
                logging.getLogger(__name__).warning('MEMORY_RETRIEVAL_UNAVAILABLE')
        with self.graph_store.lease(context.current_user.id,context.conversation_id):
            return await self.workflow(context).chat(user_message, history)

    async def resume_execution(self,conversation_id,execution_id,actor):
        from app.agent.task_workflow import TaskWorkflow
        context=AgentToolContext(current_user=actor,conversation_id=conversation_id)
        with self.graph_store.lease(actor.id,conversation_id):
            return await TaskWorkflow(self,context,self.graph_store).resume_execution(execution_id)

    def execution_reports(self,actor,conversation_id):
        reports=self.graph_store.executions(actor.id,conversation_id)
        available=self.graph_store.available(actor.id,conversation_id)
        for item in reports:
            if item['status']=='RUNNING' and available:
                _,uncertain=self.graph_store.runtime(item['execution_id'])
                item.update(can_resume=not uncertain,recovery_reason='WORKER_RELEASED' if not uncertain else 'WRITE_STATE_UNCERTAIN')
        return reports

    async def resume_action(self, conversation_id: int, action_id: int, actor, decision: str):
        with self.graph_store.lease(actor.id,conversation_id):
            if decision == 'confirm':
                self.pending_action_service.require_writes_enabled()
            action = self.pending_action_service._get_owned(action_id, conversation_id, actor.id, for_update=True)
            # Business state wins over a stale checkpoint; ordinary duplicate
            # confirm remains 409. Explicit recovery only verifies its receipt.
            self.pending_action_service._require_pending(action)
            context = AgentToolContext(current_user=actor, conversation_id=conversation_id, pending_action_id=action_id)
            return await self.workflow(context).resume(action_id, decision)

    @staticmethod
    def _validate_history(history: Sequence[AgentModelMessage]) -> None:
        for message in history:
            if message.role not in {AgentMessageRole.USER, AgentMessageRole.ASSISTANT}:
                raise ValueError('Agent history may contain only user and assistant messages')
            if message.tool_calls or message.tool_call_id is not None:
                raise ValueError('Agent history cannot contain tool calls or tool results')
