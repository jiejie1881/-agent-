from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, String, UniqueConstraint, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.models.mixins import TimestampMixin


class DriverAttendance(TimestampMixin, Base):
    __tablename__ = "driver_attendances"
    __table_args__ = (
        UniqueConstraint("driver_id", "date", "period", name="uq_driver_attendance_shift"),
        CheckConstraint("period IN ('MORNING', 'AFTERNOON')", name="ck_driver_attendance_period"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    period: Mapped[str] = mapped_column(String(20))
    available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    override_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class DriverAttendanceRule(TimestampMixin, Base):
    __tablename__ = "driver_attendance_rules"
    __table_args__ = (
        UniqueConstraint("driver_id", "effective_date", "period", name="uq_driver_fixed_attendance"),
        CheckConstraint("period IN ('MORNING', 'AFTERNOON')", name="ck_driver_fixed_attendance_period"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    effective_date: Mapped[date] = mapped_column(Date, index=True)
    period: Mapped[str] = mapped_column(String(20))
    available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class DriverSchedule(TimestampMixin, Base):
    __tablename__ = "driver_schedules"
    __table_args__ = (
        UniqueConstraint("date", "period", "vehicle_id", name="uq_schedule_vehicle_shift"),
        UniqueConstraint("date", "period", "driver_id", name="uq_schedule_driver_shift"),
        CheckConstraint("period IN ('MORNING', 'AFTERNOON')", name="ck_schedule_period"),
        CheckConstraint("kind IN ('NORMAL', 'SUBSTITUTE')", name="ck_schedule_kind"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    period: Mapped[str] = mapped_column(String(20))
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="RESTRICT"), index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    original_driver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(20), default="NORMAL")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class DriverLeave(TimestampMixin, Base):
    __tablename__ = "driver_leaves"
    __table_args__ = (
        CheckConstraint("start_date <= end_date", name="ck_leave_date_range"),
        CheckConstraint("period IN ('MORNING', 'AFTERNOON', 'ALL_DAY')", name="ck_leave_period"),
        CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED')", name="ck_leave_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date] = mapped_column(Date)
    period: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(500))
    remark: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    leave_type: Mapped[str] = mapped_column(String(50), default="OTHER", server_default="OTHER")
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_remark: Mapped[str | None] = mapped_column(String(1000))


class DriverSubstitution(TimestampMixin, Base):
    __tablename__ = "driver_substitutions"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING', 'CONFIRMED', 'CANCELLED')", name="ck_substitution_status"),
        CheckConstraint("period IN ('MORNING', 'AFTERNOON')", name="ck_substitution_period"),
        UniqueConstraint("date", "period", "active_vehicle_id", name="uq_substitution_vehicle"),
        UniqueConstraint("date", "period", "active_driver_id", name="uq_substitution_driver"),
        CheckConstraint("(status = 'CONFIRMED' AND active_vehicle_id IS NOT NULL AND active_driver_id IS NOT NULL AND active_vehicle_id = vehicle_id AND active_driver_id = substitute_driver_id) OR (status != 'CONFIRMED' AND active_vehicle_id IS NULL AND active_driver_id IS NULL)", name="ck_substitution_active"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    leave_request_id: Mapped[int | None] = mapped_column(ForeignKey("driver_leaves.id", ondelete="RESTRICT"), index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="RESTRICT"))
    original_driver_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    substitute_driver_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    date: Mapped[date] = mapped_column(Date, index=True)
    period: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    # Nullable active keys allow cancelled history while enforcing live uniqueness in MySQL/SQLite.
    active_vehicle_id: Mapped[int | None] = mapped_column(Integer)
    active_driver_id: Mapped[int | None] = mapped_column(Integer)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
