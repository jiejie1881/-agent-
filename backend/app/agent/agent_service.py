from __future__ import annotations

from collections.abc import Sequence

from app.agent.chat_types import AgentChatResult
from app.agent.exceptions import (
    AgentMaxToolCallsError,
    AgentModelResponseError,
)
from app.agent.model_client import AgentModelClient
from app.agent.model_types import AgentMessageRole, AgentModelMessage
from app.agent.prompts.system_prompt import AGENT_SYSTEM_PROMPT
from app.agent.tool_execution import AgentToolContext, AgentToolExecutorRegistry
from app.agent.tool_registry import AgentToolRegistry
from app.core.config import get_settings


class AgentService:
    def __init__(
        self,
        model_client: AgentModelClient,
        tool_registry: AgentToolRegistry,
        executor_registry: AgentToolExecutorRegistry,
        *,
        max_tool_calls: int | None = None,
        system_prompt: str = AGENT_SYSTEM_PROMPT,
    ) -> None:
        configured_limit = (
            get_settings().agent_max_tool_calls
            if max_tool_calls is None
            else max_tool_calls
        )
        if configured_limit < 1:
            raise ValueError("max_tool_calls must be at least 1")
        self.model_client = model_client
        self.tool_registry = tool_registry
        self.executor_registry = executor_registry
        self.max_tool_calls = configured_limit
        self.system_prompt = system_prompt

    async def chat(
        self,
        user_message: str,
        context: AgentToolContext,
        history: Sequence[AgentModelMessage] = (),
    ) -> AgentChatResult:
        self._validate_history(history)
        messages = [
            AgentModelMessage(
                role=AgentMessageRole.SYSTEM,
                content=self.system_prompt,
            ),
            *history,
            AgentModelMessage(
                role=AgentMessageRole.USER,
                content=user_message,
            ),
        ]
        model_tools = self.tool_registry.to_openai_tools()
        tool_calls_count = 0
        used_tools: list[str] = []

        while True:
            response = await self.model_client.chat(messages, model_tools)
            if not response.has_tool_calls:
                if response.content is None or not response.content.strip():
                    raise AgentModelResponseError("Agent模型未返回最终回答")
                messages.append(
                    AgentModelMessage(
                        role=AgentMessageRole.ASSISTANT,
                        content=response.content,
                    )
                )
                return AgentChatResult(
                    content=response.content,
                    tool_calls_count=tool_calls_count,
                    used_tools=tuple(used_tools),
                )

            messages.append(
                AgentModelMessage(
                    role=AgentMessageRole.ASSISTANT,
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )
            for tool_call in response.tool_calls:
                if tool_calls_count >= self.max_tool_calls:
                    raise AgentMaxToolCallsError(self.max_tool_calls)

                self.tool_registry.validate_arguments(
                    tool_call.name,
                    tool_call.arguments,
                )
                tool_calls_count += 1
                result = await self.executor_registry.execute(
                    tool_call.name,
                    tool_call.arguments,
                    context,
                )
                used_tools.append(tool_call.name)
                messages.append(
                    AgentModelMessage(
                        role=AgentMessageRole.TOOL,
                        tool_call_id=tool_call.id,
                        content=result.to_json(),
                    )
                )

    @staticmethod
    def _validate_history(history: Sequence[AgentModelMessage]) -> None:
        for message in history:
            if message.role not in {
                AgentMessageRole.USER,
                AgentMessageRole.ASSISTANT,
            }:
                raise ValueError(
                    "Agent history may contain only user and assistant messages"
                )
            if message.tool_calls or message.tool_call_id is not None:
                raise ValueError(
                    "Agent history cannot contain tool calls or tool results"
                )
