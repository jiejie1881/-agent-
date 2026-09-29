from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import User
from app.repositories.audit_log_repository import AuditLogRepository


class AuditAction:
    LOGIN = "LOGIN"
    DELIVERY_DEMAND_CREATED = "DELIVERY_DEMAND_CREATED"
    DELIVERY_DEMAND_UPDATED = "DELIVERY_DEMAND_UPDATED"
    AUTO_DISPATCH_GENERATED = "AUTO_DISPATCH_GENERATED"
    DISPATCH_DEMAND_MOVED = "DISPATCH_DEMAND_MOVED"
    DISPATCH_PLAN_PUBLISHED = "DISPATCH_PLAN_PUBLISHED"
    DISPATCH_PLAN_CANCELLED = "DISPATCH_PLAN_CANCELLED"
    DELIVERY_STARTED = "DELIVERY_STARTED"
    DELIVERY_COMPLETED = "DELIVERY_COMPLETED"
    USER_CREATED = "USER_CREATED"
    USER_UPDATED = "USER_UPDATED"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"


class AuditLogService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = AuditLogRepository(session)

    def add(
        self,
        actor: User,
        action: str,
        object_type: str,
        object_id: int | None,
        changes: dict[str, object] | None = None,
    ) -> AuditLog:
        log = AuditLog(
            user_id=actor.id,
            username=actor.username,
            action=action,
            object_type=object_type,
            object_id=object_id,
            changes=jsonable_encoder(changes) if changes is not None else None,
        )
        return self.repository.add(log)

    def list(
        self,
        action: str | None,
        object_type: str | None,
        user_id: int | None,
        offset: int,
        limit: int,
    ) -> list[AuditLog]:
        return self.repository.list_filtered(
            action, object_type, user_id, offset, limit
        )
