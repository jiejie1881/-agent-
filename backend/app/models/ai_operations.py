from datetime import datetime
from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.infrastructure.database.base import Base


class DemandBatchReceipt(Base):
    __tablename__ = "demand_batch_receipts"
    __table_args__ = (UniqueConstraint("actor_id", "request_key", name="uq_demand_batch_actor_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    request_key: Mapped[str] = mapped_column(String(36))
    payload_hash: Mapped[str] = mapped_column(String(64))
    demand_ids: Mapped[list[int]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DispatchQualityReport(Base):
    __tablename__ = "dispatch_quality_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("dispatch_plans.id", ondelete="RESTRICT"), index=True)
    rule_version: Mapped[str] = mapped_column(String(50))
    basis_hash: Mapped[str] = mapped_column(String(64))
    scope: Mapped[list[dict]] = mapped_column(JSON)
    report: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
