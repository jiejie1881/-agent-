from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Enum, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base
from app.models.mixins import TimestampMixin
from app.domain.enums import VehicleTypeCode


class VehicleType(TimestampMixin, Base):
    __tablename__ = "vehicle_types"
    __table_args__ = (UniqueConstraint("code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[VehicleTypeCode] = mapped_column(
        Enum(
            VehicleTypeCode,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="vehicle_type_code",
        ),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), unique=True)
    min_load: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    max_load: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="vehicle_type")
    cargo_capabilities: Mapped[list["VehicleTypeCargoCapability"]] = relationship(
        back_populates="vehicle_type", cascade="all, delete-orphan"
    )


class Vehicle(TimestampMixin, Base):
    __tablename__ = "vehicles"
    __table_args__ = (UniqueConstraint("code"), UniqueConstraint("plate_number"))

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), index=True)
    plate_number: Mapped[str] = mapped_column(String(20), index=True)
    vehicle_type_id: Mapped[int] = mapped_column(
        ForeignKey("vehicle_types.id", ondelete="RESTRICT"), index=True
    )
    driver_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        unique=True,
        index=True,
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    vehicle_type: Mapped[VehicleType] = relationship(back_populates="vehicles")
    driver: Mapped["User | None"] = relationship(back_populates="assigned_vehicle")


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


class VehicleTypeCargoCapability(TimestampMixin, Base):
    """Archive-only transport data. Not used by candidates or validators."""
    __tablename__ = "vehicle_type_cargo_capabilities"
    __table_args__ = (
        UniqueConstraint(
            "vehicle_type_id", "cargo_category_id", name="uq_vehicle_type_cargo"
        ),
        CheckConstraint(
            "(min_temperature IS NULL AND max_temperature IS NULL) OR "
            "(min_temperature IS NOT NULL AND max_temperature IS NOT NULL "
            "AND min_temperature <= max_temperature)",
            name="ck_vehicle_type_cargo_temperature_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_type_id: Mapped[int] = mapped_column(
        ForeignKey("vehicle_types.id", ondelete="CASCADE"), index=True
    )
    cargo_category_id: Mapped[int] = mapped_column(
        ForeignKey("cargo_categories.id", ondelete="RESTRICT"), index=True
    )
    is_allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    min_temperature: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    max_temperature: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )

    vehicle_type: Mapped[VehicleType] = relationship(
        back_populates="cargo_capabilities"
    )
    cargo_category: Mapped["CargoCategory"] = relationship(
        back_populates="vehicle_type_capabilities"
    )


from app.models.terrain import Terrain  # noqa: E402
from app.models.cargo_category import CargoCategory  # noqa: E402
from app.models.user import User  # noqa: E402
