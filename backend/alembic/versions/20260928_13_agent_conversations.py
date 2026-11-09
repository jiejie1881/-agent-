"""Add user-owned Agent conversations and visible messages."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260928_13"
down_revision: str | None = "20260927_12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
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
        sa.CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_agent_conversation_title_not_blank",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_conversations_user_id",
        "agent_conversations",
        ["user_id"],
    )

    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "USER",
                "ASSISTANT",
                name="agent_conversation_message_role",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(content)) > 0",
            name="ck_agent_message_content_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["agent_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_messages_conversation_id",
        "agent_messages",
        ["conversation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_messages_conversation_id",
        table_name="agent_messages",
    )
    op.drop_table("agent_messages")
    op.drop_index(
        "ix_agent_conversations_user_id",
        table_name="agent_conversations",
    )
    op.drop_table("agent_conversations")
