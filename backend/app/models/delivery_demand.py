from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, Enum, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import DeliveryDemandStatus, DeliveryPeriod
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
    status: Mapped[DeliveryDemandStatus] = mapped_column(
        Enum(
            DeliveryDemandStatus,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="delivery_demand_status",
        ),
        nullable=False,
        index=True,
        server_default=DeliveryDemandStatus.PENDING.value,
    )

    store: Mapped["Store"] = relationship()

    @property
    def core_fields_editable(self) -> bool:
        return can_edit_delivery_demand_core_fields(self.status)


from app.models.store import Store  # noqa: E402
