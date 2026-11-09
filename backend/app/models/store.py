from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base
from app.models.mixins import TimestampMixin


class Store(TimestampMixin, Base):
    __tablename__ = "stores"
    __table_args__ = (UniqueConstraint("code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    delivery_region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    route_links: Mapped[list["StoreRoute"]] = relationship(
        back_populates="store", cascade="all, delete-orphan"
    )


class StoreRoute(TimestampMixin, Base):
    __tablename__ = "store_routes"
    __table_args__ = (
        UniqueConstraint("store_id", "route_id", name="uq_store_route"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), index=True
    )
    route_id: Mapped[int] = mapped_column(
        ForeignKey("routes.id", ondelete="CASCADE"), index=True
    )

    store: Mapped[Store] = relationship(back_populates="route_links")
    route: Mapped["Route"] = relationship(back_populates="store_links")


from app.models.route import Route  # noqa: E402

