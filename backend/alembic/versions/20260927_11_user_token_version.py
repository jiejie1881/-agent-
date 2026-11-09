"""Add token version for session invalidation."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260927_11"
down_revision: str | None = "20260925_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
