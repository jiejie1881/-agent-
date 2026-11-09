from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.repositories.base import BaseRepository


class AuditLogRepository(BaseRepository[AuditLog]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, AuditLog)

    def list_filtered(
        self,
        action: str | None,
        object_type: str | None,
        user_id: int | None,
        offset: int,
        limit: int,
    ) -> list[AuditLog]:
        statement = select(AuditLog)
        if action:
            statement = statement.where(AuditLog.action == action)
        if object_type:
            statement = statement.where(AuditLog.object_type == object_type)
        if user_id is not None:
            statement = statement.where(AuditLog.user_id == user_id)
        statement = statement.order_by(AuditLog.id.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(statement))
