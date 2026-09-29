from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import AgentConversationMessageRole
from app.agent.chat_types import AgentPendingActionSnapshot


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)

    @field_validator("message", mode="before")
    @classmethod
    def normalize_message(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class AgentChatResponse(BaseModel):
    content: str
    tool_calls_count: int
    used_tools: list[str]
    request_id: str


class AgentConversationSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class AgentConversationMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: AgentConversationMessageRole
    content: str
    created_at: datetime


class AgentConversationDetailResponse(AgentConversationSummaryResponse):
    messages: list[AgentConversationMessageResponse]
    pending_actions: list[AgentPendingActionSnapshot] = Field(default_factory=list)


class AgentConversationChatResponse(BaseModel):
    conversation_id: int
    message: AgentConversationMessageResponse
    tool_calls_count: int
    used_tools: list[str]
    request_id: str
    pending_actions: list[AgentPendingActionSnapshot] = Field(default_factory=list)


class AgentPendingActionExecutionResponse(BaseModel):
    action: AgentPendingActionSnapshot
    result: dict[str, object]
