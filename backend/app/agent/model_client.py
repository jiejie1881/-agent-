import json
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from app.agent.exceptions import (
    AgentModelConfigurationError,
    AgentModelConnectionError,
    AgentModelResponseError,
    AgentModelTimeoutError,
)
from app.agent.model_types import (
    AgentMessageRole,
    AgentModelMessage,
    AgentModelResponse,
    AgentToolCall,
)
from app.core.config import Settings, get_settings

ToolDefinition = Mapping[str, Any]


class AgentModelClient(ABC):
    """Provider-independent interface consumed by the future AgentService."""

    @abstractmethod
    async def chat(
        self,
        messages: Sequence[AgentModelMessage],
        tools: Sequence[ToolDefinition] | None = None,
    ) -> AgentModelResponse:
        raise NotImplementedError


class OpenAICompatibleModelClient(AgentModelClient):
    SUPPORTED_PROVIDERS = {"openai", "openai-compatible", "openai_compatible"}

    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(provider=<configured>)"

    async def chat(
        self,
        messages: Sequence[AgentModelMessage],
        tools: Sequence[ToolDefinition] | None = None,
    ) -> AgentModelResponse:
        model, api_key, base_url = self._validated_configuration()
        payload: dict[str, Any] = {
            "model": model,
            "messages": [self._serialize_message(message) for message in messages],
        }
        if tools:
            payload["tools"] = [dict(tool) for tool in tools]

        try:
            async with httpx.AsyncClient(
                timeout=self._settings.agent_timeout,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
        except httpx.TimeoutException:
            raise AgentModelTimeoutError() from None
        except httpx.RequestError:
            raise AgentModelConnectionError() from None
        except httpx.HTTPStatusError:
            raise AgentModelResponseError("Agent模型服务返回错误状态") from None

        try:
            raw_response = response.json()
        except (ValueError, json.JSONDecodeError):
            raise AgentModelResponseError() from None
        return self._parse_response(raw_response)

    def _validated_configuration(self) -> tuple[str, str, str]:
        provider = (self._settings.agent_provider or "").strip().lower()
        model = (self._settings.agent_model or "").strip()
        base_url = (self._settings.agent_base_url or "").strip()
        api_key = (
            self._settings.agent_api_key.get_secret_value()
            if self._settings.agent_api_key is not None
            else ""
        )
        if provider not in self.SUPPORTED_PROVIDERS:
            raise AgentModelConfigurationError("不支持或未配置Agent模型Provider")
        if not model or not api_key or not base_url:
            raise AgentModelConfigurationError()
        parsed_url = urlparse(base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise AgentModelConfigurationError("AGENT_BASE_URL不是有效的HTTP地址")
        return model, api_key, base_url

    @staticmethod
    def _serialize_message(message: AgentModelMessage) -> dict[str, Any]:
        serialized: dict[str, Any] = {
            "role": message.role.value,
            "content": message.content,
        }
        if message.tool_call_id is not None:
            serialized["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            serialized["tool_calls"] = [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": json.dumps(
                            tool_call.arguments,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    },
                }
                for tool_call in message.tool_calls
            ]
        return serialized

    @classmethod
    def _parse_response(cls, payload: object) -> AgentModelResponse:
        if not isinstance(payload, dict):
            raise AgentModelResponseError()
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AgentModelResponseError()
        choice = choices[0]
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            raise AgentModelResponseError()
        message = choice["message"]
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise AgentModelResponseError()
        raw_tool_calls = message.get("tool_calls") or []
        if not isinstance(raw_tool_calls, list):
            raise AgentModelResponseError()
        try:
            tool_calls = tuple(
                cls._parse_tool_call(raw_tool_call)
                for raw_tool_call in raw_tool_calls
            )
            response = AgentModelResponse(
                content=content,
                tool_calls=tool_calls,
                finish_reason=(
                    choice.get("finish_reason")
                    if isinstance(choice.get("finish_reason"), str)
                    else None
                ),
            )
        except (ValidationError, TypeError, ValueError):
            raise AgentModelResponseError() from None
        if response.content is None and not response.tool_calls:
            raise AgentModelResponseError()
        return response

    @staticmethod
    def _parse_tool_call(raw_tool_call: object) -> AgentToolCall:
        if not isinstance(raw_tool_call, dict):
            raise AgentModelResponseError()
        function = raw_tool_call.get("function")
        if (
            raw_tool_call.get("type", "function") != "function"
            or not isinstance(function, dict)
        ):
            raise AgentModelResponseError()
        raw_arguments = function.get("arguments")
        if isinstance(raw_arguments, str):
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                raise AgentModelResponseError("Tool Call参数不是合法JSON") from None
        elif isinstance(raw_arguments, dict):
            arguments = raw_arguments
        else:
            raise AgentModelResponseError("Tool Call参数不是合法JSON对象")
        if not isinstance(arguments, dict):
            raise AgentModelResponseError("Tool Call参数必须是JSON对象")
        try:
            return AgentToolCall(
                id=raw_tool_call.get("id"),
                name=function.get("name"),
                arguments=arguments,
            )
        except ValidationError:
            raise AgentModelResponseError("Tool Call结构不完整") from None
