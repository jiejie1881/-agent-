from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.infrastructure.database.base import Base
from app.models.mixins import TimestampMixin


class BusinessImport(TimestampMixin, Base):
    __tablename__ = "business_imports"
    __table_args__ = (UniqueConstraint("actor_id", "kind", "file_sha256", name="uq_business_import_file"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    file_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))
    rows: Mapped[list] = mapped_column(JSON)
    errors: Mapped[list] = mapped_column(JSON)
    result_ids: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ExceptionCase(TimestampMixin, Base):
    __tablename__ = "exception_cases"
    __table_args__ = (UniqueConstraint("source_key", name="uq_exception_source"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(default=1)


class ExceptionCaseEvent(TimestampMixin, Base):
    __tablename__ = "exception_case_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("exception_cases.id", ondelete="RESTRICT"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    before_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    after_status: Mapped[str] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
