from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

from app.agent.exceptions import (
    AgentToolArgumentsError,
    AgentToolNotFoundError,
    AgentToolRegistrationError,
)
from app.agent.schemas.tool import (
    CANCEL_DISPATCH_PLAN_DEFINITION,
    GET_DISPATCH_PLAN_DETAIL_DEFINITION,
    GET_UNASSIGNED_DEMANDS_DEFINITION,
    GET_VEHICLE_ATTENDANCE_DEFINITION,
    LIST_DELIVERY_DEMANDS_DEFINITION,
    LIST_DISPATCH_PLANS_DEFINITION,
    MOVE_DELIVERY_DEMAND_DEFINITION,
    SEARCH_KNOWLEDGE_BASE_DEFINITION,
    VALIDATE_DISPATCH_PLAN_DEFINITION,
    AgentToolDefinition,
)
from app.core.config import get_settings

DEFAULT_TOOL_DEFINITIONS: tuple[AgentToolDefinition, ...] = (
    LIST_DELIVERY_DEMANDS_DEFINITION,
    GET_VEHICLE_ATTENDANCE_DEFINITION,
    LIST_DISPATCH_PLANS_DEFINITION,
    GET_DISPATCH_PLAN_DETAIL_DEFINITION,
    GET_UNASSIGNED_DEMANDS_DEFINITION,
    VALIDATE_DISPATCH_PLAN_DEFINITION,
    SEARCH_KNOWLEDGE_BASE_DEFINITION,
)

WRITE_TOOL_DEFINITIONS: tuple[AgentToolDefinition, ...] = (
    MOVE_DELIVERY_DEMAND_DEFINITION,
    CANCEL_DISPATCH_PLAN_DEFINITION,
)


class AgentToolRegistry:
    """Explicit whitelist of model-visible tools and their argument schemas."""

    def __init__(
        self,
        definitions: Sequence[AgentToolDefinition] | None = None,
    ) -> None:
        writes_enabled = get_settings().agent_write_tools_enabled
        supplied = (DEFAULT_TOOL_DEFINITIONS + WRITE_TOOL_DEFINITIONS
                    if definitions is None else definitions)
        ordered_definitions = tuple(d for d in supplied if d.read_only or writes_enabled)
        definitions_by_name: dict[str, AgentToolDefinition] = {}
        for definition in ordered_definitions:
            if definition.name in definitions_by_name:
                raise AgentToolRegistrationError(definition.name)
            definitions_by_name[definition.name] = definition

        self._definitions = ordered_definitions
        self._definitions_by_name = definitions_by_name

    def get(self, name: str) -> AgentToolDefinition:
        if not isinstance(name, str):
            raise AgentToolNotFoundError(name)
        definition = self._definitions_by_name.get(name)
        if definition is None:
            raise AgentToolNotFoundError(name)
        return definition

    def validate_arguments(
        self,
        name: str,
        arguments: object,
    ) -> BaseModel:
        definition = self.get(name)
        try:
            # Revalidate constructed model instances as well as raw JSON;
            # model_construct() must not bypass field-level safety checks.
            if isinstance(arguments, BaseModel):
                arguments = arguments.model_dump(mode='python')
            return definition.arguments_schema.model_validate(arguments)
        except ValidationError as exc:
            raise AgentToolArgumentsError(name) from exc

    def list_definitions(self) -> tuple[AgentToolDefinition, ...]:
        return self._definitions

    def to_openai_tools(self) -> list[dict[str, Any]]:
        return [definition.to_openai_tool() for definition in self._definitions]
