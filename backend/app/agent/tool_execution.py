from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, TypeAdapter

from app.agent.exceptions import (
    AgentToolArgumentsError,
    AgentToolError,
    AgentToolExecutionError,
    AgentToolNotFoundError,
    AgentToolRegistrationError,
)
from app.agent.tool_registry import AgentToolRegistry
from app.domain.exceptions import BusinessError
from app.models.user import User


ArgsT = TypeVar("ArgsT", bound=BaseModel)
_JSON_ADAPTER = TypeAdapter(Any)


@dataclass(frozen=True, slots=True)
class AgentToolContext:
    current_user: User
    request_id: str | None = None


class AgentToolResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str
    data: dict[str, Any]

    @classmethod
    def from_data(cls, tool_name: str, data: dict[str, Any]) -> "AgentToolResult":
        normalized = _JSON_ADAPTER.dump_python(data, mode="json")
        if not isinstance(normalized, dict):
            raise TypeError("Agent Tool result data must be an object")
        return cls(tool_name=tool_name, data=normalized)

    def to_json(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False)


class AgentToolExecutor(ABC, Generic[ArgsT]):
    name: str
    arguments_type: type[ArgsT]

    async def execute(
        self,
        arguments: BaseModel,
        context: AgentToolContext,
    ) -> AgentToolResult:
        if not isinstance(arguments, self.arguments_type):
            raise AgentToolArgumentsError(self.name)
        try:
            data = self._execute(arguments, context)
            return AgentToolResult.from_data(self.name, data)
        except AgentToolError:
            raise
        except BusinessError as exc:
            raise AgentToolExecutionError(
                self.name,
                exc.message,
                status_code=exc.status_code,
            ) from exc
        except Exception as exc:
            raise AgentToolExecutionError(self.name) from exc

    @abstractmethod
    def _execute(
        self,
        arguments: ArgsT,
        context: AgentToolContext,
    ) -> dict[str, Any]:
        raise NotImplementedError


class AgentToolExecutorRegistry:
    """Explicit mapping between whitelisted definitions and executors."""

    def __init__(
        self,
        executors: list[AgentToolExecutor[Any]],
        definition_registry: AgentToolRegistry | None = None,
    ) -> None:
        self.definition_registry = definition_registry or AgentToolRegistry()
        executors_by_name: dict[str, AgentToolExecutor[Any]] = {}
        for executor in executors:
            self.definition_registry.get(executor.name)
            if executor.name in executors_by_name:
                raise AgentToolRegistrationError(executor.name)
            executors_by_name[executor.name] = executor
        self._executors_by_name = executors_by_name

    async def execute(
        self,
        name: str,
        arguments: object,
        context: AgentToolContext,
    ) -> AgentToolResult:
        validated_arguments = self.definition_registry.validate_arguments(
            name, arguments
        )
        executor = self._executors_by_name.get(name)
        if executor is None:
            raise AgentToolExecutionError(name, "工具执行器未配置")
        return await executor.execute(validated_arguments, context)

    def get(self, name: str) -> AgentToolExecutor[Any]:
        executor = self._executors_by_name.get(name)
        if executor is None:
            raise AgentToolNotFoundError(name)
        return executor
