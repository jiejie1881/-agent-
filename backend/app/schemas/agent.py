from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import AgentConversationMessageRole


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


class AgentConversationChatResponse(BaseModel):
    conversation_id: int
    message: AgentConversationMessageResponse
    tool_calls_count: int
    used_tools: list[str]
    request_id: str
