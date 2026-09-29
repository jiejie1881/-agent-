from decimal import Decimal

from sqlalchemy import Boolean, Enum, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base
from app.models.mixins import TimestampMixin
from app.domain.enums import VehicleTypeCode


class VehicleType(TimestampMixin, Base):
    __tablename__ = "vehicle_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[VehicleTypeCode] = mapped_column(
        Enum(
            VehicleTypeCode,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="vehicle_type_code",
        ),
        unique=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), unique=True)
    min_load: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    max_load: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="vehicle_type")


class Vehicle(TimestampMixin, Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    plate_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    vehicle_type_id: Mapped[int] = mapped_column(
        ForeignKey("vehicle_types.id", ondelete="RESTRICT"), index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    vehicle_type: Mapped[VehicleType] = relationship(back_populates="vehicles")


class VehicleTypeTerrainPermission(TimestampMixin, Base):
    __tablename__ = "vehicle_type_terrain_permissions"
    __table_args__ = (
        UniqueConstraint(
            "vehicle_type_id", "terrain_id", name="uq_vehicle_type_terrain"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_type_id: Mapped[int] = mapped_column(
        ForeignKey("vehicle_types.id", ondelete="CASCADE"), index=True
    )
    terrain_id: Mapped[int] = mapped_column(
        ForeignKey("terrains.id", ondelete="CASCADE"), index=True
    )

    vehicle_type: Mapped[VehicleType] = relationship()
    terrain: Mapped["Terrain"] = relationship()


from app.models.terrain import Terrain  # noqa: E402
