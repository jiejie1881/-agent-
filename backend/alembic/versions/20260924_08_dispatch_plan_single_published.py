"""Allow only one published dispatch plan for each delivery date."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260924_08"
down_revision: str | None = "20260924_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    dialect_name = op.get_bind().dialect.name
    if dialect_name == "mysql":
        op.execute(
            sa.text(
                "UPDATE dispatch_plans AS older "
                "JOIN dispatch_plans AS newer "
                "ON newer.delivery_date = older.delivery_date "
                "AND newer.status = 'PUBLISHED' "
                "AND newer.version > older.version "
                "SET older.status = 'CANCELLED' "
                "WHERE older.status = 'PUBLISHED'"
            )
        )
    else:
        op.execute(
            sa.text(
                "UPDATE dispatch_plans AS older SET status = 'CANCELLED' "
                "WHERE status = 'PUBLISHED' AND EXISTS ("
                "SELECT 1 FROM dispatch_plans AS newer "
                "WHERE newer.delivery_date = older.delivery_date "
                "AND newer.status = 'PUBLISHED' "
                "AND newer.version > older.version)"
            )
        )

    op.add_column(
        "dispatch_plans",
        sa.Column(
            "published_delivery_date",
            sa.Date(),
            sa.Computed(
                "CASE WHEN status = 'PUBLISHED' "
                "THEN delivery_date ELSE NULL END",
                persisted=False,
            ),
            nullable=True,
        ),
    )
    op.create_index(
        "uq_dispatch_plan_published_date",
        "dispatch_plans",
        ["published_delivery_date"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_dispatch_plan_published_date", table_name="dispatch_plans"
    )
    op.drop_column("dispatch_plans", "published_delivery_date")
