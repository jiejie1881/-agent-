"""Durable provenance and replay protection for Agent-created plans."""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class DispatchDateGuard(Base):
    __tablename__ = "dispatch_date_guards"

    delivery_date: Mapped[date] = mapped_column(Date, primary_key=True)


class AgentDispatchPlanSource(Base):
    __tablename__ = "agent_dispatch_plan_sources"

    plan_id: Mapped[int] = mapped_column(ForeignKey("dispatch_plans.id", ondelete="RESTRICT"), primary_key=True)
    receipt_nonce_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_snapshot_version: Mapped[str] = mapped_column(String(64), nullable=False)
    post_save_snapshot_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentDispatchOperation(Base):
    __tablename__ = "agent_dispatch_operations"
    __table_args__ = (UniqueConstraint("actor_id", "operation", "idempotency_key",
                                     name="uq_agent_dispatch_operation_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_nonce_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    plan_id: Mapped[int] = mapped_column(ForeignKey("dispatch_plans.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
