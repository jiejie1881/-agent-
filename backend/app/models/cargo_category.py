from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base
from app.models.mixins import TimestampMixin


class CargoCategory(TimestampMixin, Base):
    """Archive-only mapping retained for historical FKs; no current business API."""
    __tablename__ = "cargo_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    demands: Mapped[list["DeliveryDemand"]] = relationship(
        back_populates="cargo_category"
    )
    vehicle_type_capabilities: Mapped[list["VehicleTypeCargoCapability"]] = (
        relationship(back_populates="cargo_category")
    )


from app.models.delivery_demand import DeliveryDemand  # noqa: E402
from app.models.vehicle import VehicleTypeCargoCapability  # noqa: E402
