"""Add optional persisted coordinates to stores."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260930_15"
down_revision: str | None = "20260929_14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("stores", sa.Column("longitude", sa.Numeric(10, 7), nullable=True))
    op.add_column("stores", sa.Column("latitude", sa.Numeric(10, 7), nullable=True))


def downgrade() -> None:
    op.drop_column("stores", "latitude")
    op.drop_column("stores", "longitude")
