"""Default newly created delivery demands to pending."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260924_09"
down_revision: str | None = "20260924_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("delivery_demands") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=20),
            existing_nullable=False,
            server_default="PENDING",
        )


def downgrade() -> None:
    with op.batch_alter_table("delivery_demands") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=20),
            existing_nullable=False,
            server_default=None,
        )
