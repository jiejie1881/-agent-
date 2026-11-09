"""Add per-stop delivery execution status and proof images."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261001_18"
down_revision: str | None = "20261001_17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STOP_STATUS = sa.Enum(
    "PENDING",
    "ARRIVED",
    "SIGNED",
    "FAILED",
    name="delivery_stop_status",
    native_enum=False,
    create_constraint=True,
)
FAILURE_REASON = sa.Enum(
    "STORE_CLOSED",
    "REJECTED",
    "ADDRESS_ERROR",
    "CARGO_DAMAGED",
    "OTHER",
    name="delivery_failure_reason",
    native_enum=False,
    create_constraint=True,
)


def _add_stop_columns(batch_op) -> None:
    batch_op.add_column(
        sa.Column(
            "delivery_status",
            STOP_STATUS,
            nullable=False,
            server_default="PENDING",
        )
    )
    batch_op.add_column(sa.Column("arrived_at", sa.DateTime(timezone=True)))
    batch_op.add_column(sa.Column("signed_at", sa.DateTime(timezone=True)))
    batch_op.add_column(sa.Column("receiver_name", sa.String(length=100)))
    batch_op.add_column(sa.Column("receiver_phone", sa.String(length=30)))
    batch_op.add_column(sa.Column("failure_reason", FAILURE_REASON))
    batch_op.add_column(sa.Column("driver_remark", sa.Text()))
    batch_op.create_index(
        "ix_dispatch_order_details_delivery_status", ["delivery_status"]
    )


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(
            "dispatch_order_details", recreate="always"
        ) as batch_op:
            _add_stop_columns(batch_op)
    else:
        with op.batch_alter_table("dispatch_order_details") as batch_op:
            _add_stop_columns(batch_op)

    op.create_table(
        "delivery_proofs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dispatch_order_detail_id", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(length=255), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["dispatch_order_detail_id"],
            ["dispatch_order_details.id"],
            name="fk_delivery_proofs_stop",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_path", name="uq_delivery_proofs_file_path"),
    )
    op.create_index(
        "ix_delivery_proofs_dispatch_order_detail_id",
        "delivery_proofs",
        ["dispatch_order_detail_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_delivery_proofs_dispatch_order_detail_id",
        table_name="delivery_proofs",
    )
    op.drop_table("delivery_proofs")

    columns = (
        "driver_remark",
        "failure_reason",
        "receiver_phone",
        "receiver_name",
        "signed_at",
        "arrived_at",
        "delivery_status",
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(
            "dispatch_order_details", recreate="always"
        ) as batch_op:
            batch_op.drop_index("ix_dispatch_order_details_delivery_status")
            batch_op.drop_constraint(
                "delivery_failure_reason", type_="check"
            )
            batch_op.drop_constraint("delivery_stop_status", type_="check")
            for column in columns:
                batch_op.drop_column(column)
    else:
        with op.batch_alter_table("dispatch_order_details") as batch_op:
            batch_op.drop_index("ix_dispatch_order_details_delivery_status")
            for column in columns:
                batch_op.drop_column(column)
