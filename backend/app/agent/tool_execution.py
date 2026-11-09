from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from app.agent.exceptions import (
    AgentToolArgumentsError,
    AgentToolError,
    AgentToolExecutionError,
    AgentToolNotFoundError,
    AgentToolRegistrationError,
)
from app.agent.tool_registry import AgentToolRegistry
from app.domain.exceptions import BusinessError, PermissionDeniedError
from app.domain.permissions import has_permission
from app.models.user import User


ArgsT = TypeVar("ArgsT", bound=BaseModel)
_JSON_ADAPTER = TypeAdapter(Any)
# Bound interactive model context and memory use. Large results need the
# existing paginated business endpoints rather than silently truncated facts.
MAX_TOOL_RESULT_BYTES = 1_048_576


def _check_json_keys(value: Any) -> None:
    if isinstance(value, dict):
        if any(type(key) is not str for key in value):
            raise ValueError('Tool result object keys must be strings')
        for item in value.values():
            _check_json_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check_json_keys(item)
    elif isinstance(value, (set, frozenset)):
        raise ValueError('Tool results cannot contain unordered sets')
    elif isinstance(value, float) and not math.isfinite(value):
        # Pydantic's JSON-mode normalization can turn NaN/Infinity into null.
        # Reject the original value before normalization can erase the error.
        raise ValueError('Tool results cannot contain non-finite numbers')
    elif isinstance(value, Decimal) and not value.is_finite():
        raise ValueError('Tool results cannot contain non-finite decimal numbers')


@dataclass(frozen=True, slots=True)
class AgentToolContext:
    current_user: User
    request_id: str | None = None
    conversation_id: int | None = None
    pending_action_id: int | None = None
    memory_context: str = ''


class AgentToolResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid', revalidate_instances='always')

    tool_name: str = Field(pattern=r'^[a-z][a-z0-9_]*$', max_length=100)
    data: dict[str, Any]

    @field_validator('data', mode='before')
    @classmethod
    def validate_json_data(cls, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError('Agent Tool result data must be an object')
        _check_json_keys(data)
        normalized = _JSON_ADAPTER.dump_python(data, mode='json')
        encoded = json.dumps(normalized, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(encoded) > MAX_TOOL_RESULT_BYTES:
            raise ValueError('Agent Tool result exceeds the interactive size limit')
        return normalized

    @classmethod
    def from_data(cls, tool_name: str, data: dict[str, Any]) -> "AgentToolResult":
        if not isinstance(data, dict):
            raise TypeError("Agent Tool result data must be an object")
        return cls(tool_name=tool_name, data=data)

    def to_json(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False)


class AgentToolExecutor(ABC, Generic[ArgsT]):
    name: str
    arguments_type: type[ArgsT]
    preserve_business_errors: bool = False

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
            if self.preserve_business_errors:
                raise
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
        definition = self.definition_registry.get(name)
        actor = context.current_user
        try:
            permitted = actor is not None and actor.is_active and has_permission(actor.role, definition.required_permission)
        except (AttributeError, KeyError, TypeError):
            permitted = False
        if not permitted:
            raise PermissionDeniedError()
        validated_arguments = self.definition_registry.validate_arguments(
            name, arguments
        )
        executor = self._executors_by_name.get(name)
        if executor is None:
            raise AgentToolExecutionError(name, "工具执行器未配置")
        result = await executor.execute(validated_arguments, context)
        try:
            # Custom executors share the same boundary as built-in executors.
            # Never allow a wrong tool envelope or unserializable result to
            # become a successful checkpoint/model observation.
            if not isinstance(result, AgentToolResult):
                raise ValueError('Tool result envelope is invalid')
            result = AgentToolResult.model_validate(result)
            if result.tool_name != name:
                raise ValueError('Tool result name does not match the requested tool')
        except Exception as exc:
            raise AgentToolExecutionError(name) from exc
        return result

    def get(self, name: str) -> AgentToolExecutor[Any]:
        executor = self._executors_by_name.get(name)
        if executor is None:
            raise AgentToolNotFoundError(name)
        return executor
