"""Add the formal delivery demand status state enum."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260924_05"
down_revision: str | None = "20260924_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = (
    "PENDING",
    "PLANNED",
    "PUBLISHED",
    "DELIVERING",
    "COMPLETED",
    "CANCELLED",
)


def upgrade() -> None:
    allowed = ", ".join(f"'{status}'" for status in STATUSES)
    op.execute(
        sa.text(
            f"UPDATE delivery_demands SET status = 'PENDING' "
            f"WHERE status NOT IN ({allowed})"
        )
    )
    with op.batch_alter_table("delivery_demands") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=30),
            type_=sa.String(length=20),
            existing_nullable=False,
        )
        batch_op.create_check_constraint(
            "delivery_demand_status",
            f"status IN ({allowed})",
        )


def downgrade() -> None:
    with op.batch_alter_table("delivery_demands") as batch_op:
        batch_op.drop_constraint(
            "delivery_demand_status", type_="check"
        )
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=20),
            type_=sa.String(length=30),
            existing_nullable=False,
        )

