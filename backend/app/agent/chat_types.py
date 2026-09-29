from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.domain.enums import AgentPendingActionStatus


class AgentPendingActionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: int
    tool_name: str
    summary: str
    display_data: dict[str, Any]
    risk_level: str
    risk_message: str
    status: AgentPendingActionStatus
    created_at: datetime
    expires_at: datetime
    confirmed_at: datetime | None = None
    executed_at: datetime | None = None


class AgentChatResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str
    tool_calls_count: int
    used_tools: tuple[str, ...] = ()
    pending_actions: tuple[AgentPendingActionSnapshot, ...] = ()
