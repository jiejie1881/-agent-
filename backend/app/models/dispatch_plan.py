from datetime import date
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Computed,
    Date,
    Enum,
    ForeignKey,
    Numeric,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import DeliveryPeriod, DispatchPlanStatus
from app.infrastructure.database.base import Base
from app.models.mixins import TimestampMixin


class DispatchPlan(TimestampMixin, Base):
    __tablename__ = "dispatch_plans"
    __table_args__ = (
        UniqueConstraint(
            "delivery_date", "version", name="uq_dispatch_plan_date_version"
        ),
        CheckConstraint("version > 0", name="ck_dispatch_plan_version_positive"),
        Index(
            "uq_dispatch_plan_published_date",
            "published_delivery_date",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_date: Mapped[date] = mapped_column(Date, index=True)
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[DispatchPlanStatus] = mapped_column(
        Enum(
            DispatchPlanStatus,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="dispatch_plan_status",
        ),
        index=True,
    )
    published_delivery_date: Mapped[date | None] = mapped_column(
        Date,
        Computed(
            "CASE WHEN status = 'PUBLISHED' THEN delivery_date ELSE NULL END",
            persisted=False,
        ),
        nullable=True,
    )
    orders: Mapped[list["DispatchOrder"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    unassigned_demands: Mapped[list["DispatchPlanUnassignedDemand"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class DispatchOrder(Base):
    __tablename__ = "dispatch_orders"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "vehicle_id",
            "period",
            "trip_no",
            name="uq_dispatch_order_vehicle_trip",
        ),
        CheckConstraint("trip_no > 0", name="ck_dispatch_order_trip_no_positive"),
        CheckConstraint("total_load > 0", name="ck_dispatch_order_load_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("dispatch_plans.id", ondelete="CASCADE"), index=True
    )
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), index=True
    )
    period: Mapped[DeliveryPeriod] = mapped_column(
        Enum(
            DeliveryPeriod,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="dispatch_order_period",
        )
    )
    trip_no: Mapped[int] = mapped_column(nullable=False)
    route_id: Mapped[int] = mapped_column(
        ForeignKey("routes.id", ondelete="RESTRICT"), index=True
    )
    total_load: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    plan: Mapped[DispatchPlan] = relationship(back_populates="orders")
    vehicle: Mapped["Vehicle"] = relationship()
    route: Mapped["Route"] = relationship()
    details: Mapped[list["DispatchOrderDetail"]] = relationship(
        back_populates="dispatch_order", cascade="all, delete-orphan"
    )


class DispatchOrderDetail(Base):
    __tablename__ = "dispatch_order_details"
    __table_args__ = (
        UniqueConstraint(
            "dispatch_order_id",
            "delivery_demand_id",
            name="uq_dispatch_order_demand",
        ),
        CheckConstraint(
            "quantity > 0", name="ck_dispatch_order_detail_quantity_positive"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dispatch_order_id: Mapped[int] = mapped_column(
        ForeignKey("dispatch_orders.id", ondelete="CASCADE"), index=True
    )
    delivery_demand_id: Mapped[int] = mapped_column(
        ForeignKey("delivery_demands.id", ondelete="RESTRICT"), index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    dispatch_order: Mapped[DispatchOrder] = relationship(back_populates="details")
    delivery_demand: Mapped["DeliveryDemand"] = relationship()


class DispatchPlanUnassignedDemand(Base):
    __tablename__ = "dispatch_plan_unassigned_demands"
    __table_args__ = (
        UniqueConstraint(
            "plan_id", "delivery_demand_id", name="uq_plan_unassigned_demand"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("dispatch_plans.id", ondelete="CASCADE"), index=True
    )
    delivery_demand_id: Mapped[int] = mapped_column(
        ForeignKey("delivery_demands.id", ondelete="RESTRICT"), index=True
    )
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    plan: Mapped[DispatchPlan] = relationship(back_populates="unassigned_demands")
    delivery_demand: Mapped["DeliveryDemand"] = relationship()


from app.models.delivery_demand import DeliveryDemand  # noqa: E402
from app.models.route import Route  # noqa: E402
from app.models.vehicle import Vehicle  # noqa: E402
