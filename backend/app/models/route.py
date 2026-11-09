from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base
from app.models.mixins import TimestampMixin


class Route(TimestampMixin, Base):
    __tablename__ = "routes"
    __table_args__ = (UniqueConstraint("code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    end_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    geographic_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(nullable=True)
    route_data_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    store_links: Mapped[list["StoreRoute"]] = relationship(
        back_populates="route", cascade="all, delete-orphan"
    )
    terrain_configs: Mapped[list["RouteTerrainConfig"]] = relationship(
        back_populates="route", cascade="all, delete-orphan"
    )


class RouteTerrainConfig(TimestampMixin, Base):
    __tablename__ = "route_terrain_configs"
    __table_args__ = (
        UniqueConstraint("route_id", "effective_date", name="uq_route_terrain_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    route_id: Mapped[int] = mapped_column(
        ForeignKey("routes.id", ondelete="CASCADE"), index=True
    )
    terrain_id: Mapped[int] = mapped_column(
        ForeignKey("terrains.id", ondelete="RESTRICT"), index=True
    )
    effective_date: Mapped[date] = mapped_column(Date, index=True)

    route: Mapped[Route] = relationship(back_populates="terrain_configs")
    terrain: Mapped["Terrain"] = relationship(back_populates="route_configs")


from app.models.store import StoreRoute  # noqa: E402
from app.models.terrain import Terrain  # noqa: E402
