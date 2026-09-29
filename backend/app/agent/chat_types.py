from pydantic import BaseModel, ConfigDict


class AgentChatResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str
    tool_calls_count: int
    used_tools: tuple[str, ...] = ()
