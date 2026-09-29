"""Add the last-updated timestamp to dispatch plans."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260924_07"
down_revision: str | None = "20260924_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dispatch_plans",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("dispatch_plans", "updated_at")
