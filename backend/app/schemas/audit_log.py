from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    username: str
    action: str
    object_type: str
    object_id: int | None
    changes: dict[str, object] | None
    created_at: datetime
