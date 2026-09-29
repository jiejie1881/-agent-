"""Add vehicle attendance and delivery demand tables."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260924_02"
down_revision: str | None = "20260924_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "vehicle_attendances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["vehicle_id"], ["vehicles.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "date", "vehicle_id", name="uq_attendance_date_vehicle"
        ),
    )
    op.create_index(
        "ix_vehicle_attendances_date", "vehicle_attendances", ["date"]
    )
    op.create_index(
        "ix_vehicle_attendances_vehicle_id", "vehicle_attendances", ["vehicle_id"]
    )

    op.create_table(
        "delivery_demands",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column(
            "period",
            sa.Enum(
                "MORNING",
                "AFTERNOON",
                name="delivery_period",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint(
            "quantity > 0", name="ck_delivery_demand_quantity_positive"
        ),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "date", "store_id", "period", name="uq_demand_date_store_period"
        ),
    )
    op.create_index("ix_delivery_demands_date", "delivery_demands", ["date"])
    op.create_index(
        "ix_delivery_demands_store_id", "delivery_demands", ["store_id"]
    )
    op.create_index("ix_delivery_demands_period", "delivery_demands", ["period"])
    op.create_index("ix_delivery_demands_status", "delivery_demands", ["status"])


def downgrade() -> None:
    op.drop_table("delivery_demands")
    op.drop_table("vehicle_attendances")

