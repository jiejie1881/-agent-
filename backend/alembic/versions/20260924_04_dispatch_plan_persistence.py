"""Persist versioned dispatch plans, orders, details and unassigned demands."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260924_04"
down_revision: str | None = "20260924_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dispatch_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("delivery_date", sa.Date(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT",
                "PUBLISHED",
                "CANCELLED",
                name="dispatch_plan_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version > 0", name="ck_dispatch_plan_version_positive"
        ),
        sa.UniqueConstraint(
            "delivery_date", "version", name="uq_dispatch_plan_date_version"
        ),
    )
    op.create_index(
        "ix_dispatch_plans_delivery_date", "dispatch_plans", ["delivery_date"]
    )
    op.create_index("ix_dispatch_plans_status", "dispatch_plans", ["status"])

    op.create_table(
        "dispatch_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column(
            "period",
            sa.Enum(
                "MORNING",
                "AFTERNOON",
                name="dispatch_order_period",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("trip_no", sa.Integer(), nullable=False),
        sa.Column("route_id", sa.Integer(), nullable=False),
        sa.Column("total_load", sa.Numeric(12, 2), nullable=False),
        sa.CheckConstraint(
            "trip_no > 0", name="ck_dispatch_order_trip_no_positive"
        ),
        sa.CheckConstraint(
            "total_load > 0", name="ck_dispatch_order_load_positive"
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["dispatch_plans.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"], ["vehicles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["route_id"], ["routes.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "plan_id",
            "vehicle_id",
            "period",
            "trip_no",
            name="uq_dispatch_order_vehicle_trip",
        ),
    )
    op.create_index("ix_dispatch_orders_plan_id", "dispatch_orders", ["plan_id"])
    op.create_index(
        "ix_dispatch_orders_vehicle_id", "dispatch_orders", ["vehicle_id"]
    )
    op.create_index(
        "ix_dispatch_orders_route_id", "dispatch_orders", ["route_id"]
    )

    op.create_table(
        "dispatch_order_details",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dispatch_order_id", sa.Integer(), nullable=False),
        sa.Column("delivery_demand_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.CheckConstraint(
            "quantity > 0", name="ck_dispatch_order_detail_quantity_positive"
        ),
        sa.ForeignKeyConstraint(
            ["dispatch_order_id"], ["dispatch_orders.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["delivery_demand_id"], ["delivery_demands.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "dispatch_order_id",
            "delivery_demand_id",
            name="uq_dispatch_order_demand",
        ),
    )
    op.create_index(
        "ix_dispatch_order_details_dispatch_order_id",
        "dispatch_order_details",
        ["dispatch_order_id"],
    )
    op.create_index(
        "ix_dispatch_order_details_delivery_demand_id",
        "dispatch_order_details",
        ["delivery_demand_id"],
    )

    op.create_table(
        "dispatch_plan_unassigned_demands",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("delivery_demand_id", sa.Integer(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["dispatch_plans.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["delivery_demand_id"], ["delivery_demands.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "plan_id", "delivery_demand_id", name="uq_plan_unassigned_demand"
        ),
    )
    op.create_index(
        "ix_dispatch_plan_unassigned_demands_plan_id",
        "dispatch_plan_unassigned_demands",
        ["plan_id"],
    )
    op.create_index(
        "ix_dispatch_plan_unassigned_demands_delivery_demand_id",
        "dispatch_plan_unassigned_demands",
        ["delivery_demand_id"],
    )


def downgrade() -> None:
    op.drop_table("dispatch_plan_unassigned_demands")
    op.drop_table("dispatch_order_details")
    op.drop_table("dispatch_orders")
    op.drop_table("dispatch_plans")

