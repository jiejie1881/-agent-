from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base
from app.models.mixins import TimestampMixin


class VehicleAttendance(TimestampMixin, Base):
    __tablename__ = "vehicle_attendances"
    __table_args__ = (
        UniqueConstraint("date", "vehicle_id", name="uq_attendance_date_vehicle"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), index=True
    )
    available: Mapped[bool] = mapped_column(Boolean, nullable=False)

    vehicle: Mapped["Vehicle"] = relationship()


from app.models.vehicle import Vehicle  # noqa: E402

