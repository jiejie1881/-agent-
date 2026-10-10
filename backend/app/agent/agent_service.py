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
                 checkpoint_path=None) -> None:
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

    async def chat(self, user_message: str, context: AgentToolContext,
                   history: Sequence[AgentModelMessage] = ()) -> AgentChatResult:
        self._validate_history(history)
        return await AgentWorkflow(self, context, self.graph_store).chat(user_message, history)

    async def resume_action(self, conversation_id: int, action_id: int, actor, decision: str):
        action = self.pending_action_service._get_owned(action_id, conversation_id, actor.id, for_update=True)
        # Business state wins if a worker died after committing MySQL but before
        # persisting its final checkpoint. A retry must never replay that write.
        self.pending_action_service._require_pending(action)
        context = AgentToolContext(current_user=actor, conversation_id=conversation_id, pending_action_id=action_id)
        return await AgentWorkflow(self, context, self.graph_store).resume(action_id, decision)

    @staticmethod
    def _validate_history(history: Sequence[AgentModelMessage]) -> None:
        for message in history:
            if message.role not in {AgentMessageRole.USER, AgentMessageRole.ASSISTANT}:
                raise ValueError('Agent history may contain only user and assistant messages')
            if message.tool_calls or message.tool_call_id is not None:
                raise ValueError('Agent history cannot contain tool calls or tool results')
