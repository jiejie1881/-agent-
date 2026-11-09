from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_user_id", "user_id"),
        Index("ix_audit_logs_action", "action"),
        Index("ix_audit_logs_object", "object_type", "object_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    object_type: Mapped[str] = mapped_column(String(50), nullable=False)
    object_id: Mapped[int | None] = mapped_column(nullable=True)
    changes: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
