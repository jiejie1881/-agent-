from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, Enum, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import DeliveryDemandStatus, DeliveryPeriod, DeliveryPriority
from app.domain.delivery_demand_policy import (
    can_edit_delivery_demand_core_fields,
)
from app.infrastructure.database.base import Base
from app.models.mixins import TimestampMixin


class DeliveryDemand(TimestampMixin, Base):
    __tablename__ = "delivery_demands"
    __table_args__ = (
        UniqueConstraint(
            "date", "store_id", "period", name="uq_demand_date_store_period"
        ),
        CheckConstraint("quantity > 0", name="ck_delivery_demand_quantity_positive"),
        CheckConstraint(
            "requires_temperature_control = 0 OR "
            "(min_temperature IS NOT NULL AND max_temperature IS NOT NULL "
            "AND min_temperature <= max_temperature)",
            name="ck_delivery_demand_temperature_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    store_id: Mapped[int] = mapped_column(
        ForeignKey("stores.id", ondelete="RESTRICT"), index=True
    )
    period: Mapped[DeliveryPeriod] = mapped_column(
        Enum(
            DeliveryPeriod,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="delivery_period",
        ),
        index=True,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Archive-only field: existing category references are retained, new demands use NULL.
    cargo_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("cargo_categories.id", ondelete="RESTRICT"), index=True, nullable=True
    )
    priority: Mapped[DeliveryPriority] = mapped_column(
        Enum(
            DeliveryPriority,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="delivery_priority",
            length=20,
        ),
        nullable=False,
        default=DeliveryPriority.NORMAL,
        server_default=DeliveryPriority.NORMAL.value,
    )
    requires_temperature_control: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    min_temperature: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    max_temperature: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    status: Mapped[DeliveryDemandStatus] = mapped_column(
        Enum(
            DeliveryDemandStatus,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="delivery_demand_status",
            length=20,
        ),
        nullable=False,
        index=True,
        server_default=DeliveryDemandStatus.PENDING.value,
    )

    store: Mapped["Store"] = relationship()
    cargo_category: Mapped["CargoCategory | None"] = relationship(back_populates="demands")

    @property
    def core_fields_editable(self) -> bool:
        return can_edit_delivery_demand_core_fields(self.status)


from app.models.store import Store  # noqa: E402
from app.models.cargo_category import CargoCategory  # noqa: E402
