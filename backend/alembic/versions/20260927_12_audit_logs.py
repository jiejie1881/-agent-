"""Add audit logs for core business actions."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260927_12"
down_revision: str | None = "20260927_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("object_type", sa.String(length=50), nullable=False),
        sa.Column("object_id", sa.Integer(), nullable=True),
        sa.Column("changes", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index(
        "ix_audit_logs_object", "audit_logs", ["object_type", "object_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_object", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_table("audit_logs")
