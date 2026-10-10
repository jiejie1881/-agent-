from datetime import date, datetime
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
    String,
    Text,
    DateTime,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import (
    DeliveryFailureReason,
    DeliveryPeriod,
    DeliveryStopStatus,
    DeliveryProofReviewStatus,
    DispatchPlanStatus,
)
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
    actual_driver_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=True
    )
    driver_username_snapshot: Mapped[str | None] = mapped_column(String(100))
    driver_name_snapshot: Mapped[str | None] = mapped_column(String(100))

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
    delivery_status: Mapped[DeliveryStopStatus] = mapped_column(
        Enum(
            DeliveryStopStatus,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="delivery_stop_status",
        ),
        nullable=False,
        default=DeliveryStopStatus.PENDING,
        server_default=DeliveryStopStatus.PENDING.value,
        index=True,
    )
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    receiver_name: Mapped[str | None] = mapped_column(String(100))
    receiver_phone: Mapped[str | None] = mapped_column(String(30))
    failure_reason: Mapped[DeliveryFailureReason | None] = mapped_column(
        Enum(
            DeliveryFailureReason,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="delivery_failure_reason",
        )
    )
    driver_remark: Mapped[str | None] = mapped_column(Text)

    dispatch_order: Mapped[DispatchOrder] = relationship(back_populates="details")
    delivery_demand: Mapped["DeliveryDemand"] = relationship()
    proofs: Mapped[list["DeliveryProof"]] = relationship(
        back_populates="stop", cascade="all, delete-orphan"
    )


class DeliveryProof(TimestampMixin, Base):
    __tablename__ = "delivery_proofs"
    __table_args__ = (UniqueConstraint("replaces_proof_id", name="uq_delivery_proof_replaces"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    dispatch_order_detail_id: Mapped[int] = mapped_column(
        ForeignKey("dispatch_order_details.id", ondelete="CASCADE"), index=True
    )
    file_path: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    review_status: Mapped[DeliveryProofReviewStatus] = mapped_column(
        Enum(DeliveryProofReviewStatus, native_enum=False, create_constraint=True,
             validate_strings=True, name="delivery_proof_review_status"),
        nullable=False, default=DeliveryProofReviewStatus.PENDING, server_default="PENDING",
    )
    # A replacement is a new immutable file; never overwrite the rejected evidence.
    replaces_proof_id: Mapped[int | None] = mapped_column(
        ForeignKey("delivery_proofs.id", ondelete="RESTRICT", name="fk_delivery_proof_replaces"), nullable=True,
    )

    stop: Mapped[DispatchOrderDetail] = relationship(back_populates="proofs")
    reviews: Mapped[list["DeliveryProofReview"]] = relationship(
        back_populates="proof", order_by="DeliveryProofReview.id",
    )


class DeliveryProofReview(Base):
    __tablename__ = "delivery_proof_reviews"
    __table_args__ = (UniqueConstraint("proof_id", name="uq_delivery_proof_review_once"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    proof_id: Mapped[int] = mapped_column(ForeignKey("delivery_proofs.id", ondelete="RESTRICT"), index=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reviewer_username: Mapped[str] = mapped_column(String(100))
    decision: Mapped[DeliveryProofReviewStatus] = mapped_column(
        Enum(DeliveryProofReviewStatus, native_enum=False, create_constraint=True,
             validate_strings=True, name="delivery_proof_review_decision"),
    )
    reason: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    proof: Mapped[DeliveryProof] = relationship(back_populates="reviews")


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
