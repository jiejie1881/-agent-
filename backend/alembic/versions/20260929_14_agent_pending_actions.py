"""Add durable Agent pending actions."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260929_14"
down_revision: str | None = "20260928_13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_pending_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("display_data", sa.JSON(), nullable=False),
        sa.Column("risk_level", sa.String(length=20), nullable=False),
        sa.Column("risk_message", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING", "CONFIRMED", "EXECUTED", "CANCELLED", "EXPIRED", "FAILED",
                name="agent_pending_action_status", native_enum=False, create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(trim(tool_name)) > 0", name="ck_agent_pending_action_tool_not_blank"),
        sa.CheckConstraint("length(trim(summary)) > 0", name="ck_agent_pending_action_summary_not_blank"),
        sa.ForeignKeyConstraint(["conversation_id"], ["agent_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_pending_actions_user_id", "agent_pending_actions", ["user_id"])
    op.create_index("ix_agent_pending_actions_conversation_id", "agent_pending_actions", ["conversation_id"])
    op.create_index("ix_agent_pending_actions_status", "agent_pending_actions", ["status"])
    op.create_index("ix_agent_pending_actions_expires_at", "agent_pending_actions", ["expires_at"])


def downgrade() -> None:
    # Dropping the table removes its indexes and foreign keys on both MySQL and
    # SQLite. MySQL rejects dropping an index that is still required by an FK.
    op.drop_table("agent_pending_actions")
