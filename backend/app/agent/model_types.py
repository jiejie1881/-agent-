from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentMessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class AgentToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any]


class AgentModelMessage(BaseModel):
    """Provider-independent message used only by the model protocol."""

    model_config = ConfigDict(frozen=True)

    role: AgentMessageRole
    content: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[AgentToolCall, ...] = ()

    @model_validator(mode="after")
    def validate_role_fields(self) -> "AgentModelMessage":
        if self.role == AgentMessageRole.TOOL and not self.tool_call_id:
            raise ValueError("tool消息必须包含tool_call_id")
        if self.role != AgentMessageRole.TOOL and self.tool_call_id is not None:
            raise ValueError("只有tool消息可以包含tool_call_id")
        if self.role != AgentMessageRole.ASSISTANT and self.tool_calls:
            raise ValueError("只有assistant消息可以包含tool_calls")
        if self.content is None and not (
            self.role == AgentMessageRole.ASSISTANT and self.tool_calls
        ):
            raise ValueError("消息必须包含content")
        return self


class AgentNetworkEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    event: str
    elapsed_ms: float = Field(ge=0)


class AgentTokenUsage(BaseModel):
    model_config = ConfigDict(frozen=True)
    input_tokens: int = Field(ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)
    total_tokens: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def consistent_total(self):
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("Token usage total mismatch")
        return self


class AgentModelResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str | None = None
    tool_calls: tuple[AgentToolCall, ...] = ()
    finish_reason: str | None = None
    token_usage: AgentTokenUsage | None = None
    network_events: tuple[AgentNetworkEvent, ...] = ()

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)
