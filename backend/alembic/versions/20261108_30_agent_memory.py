"""长期记忆核心：权威表 + 版本 + 审计 + Outbox + 会话摘要。

变更说明
--------
上一版草稿迁移（同一 revision ``20261108_30``）只创建 ``agent_user_memories``，
且从未在任何真实库执行（真实库 ``alembic_version`` 仍为 ``20261027_29``，
库内无该表）。本次按长期记忆基础设施规范重写该 revision：

- ``agent_memories``           记忆本体（租户/用户/项目隔离、软删除、过期、版本）
- ``agent_memory_versions``    版本快照
- ``agent_memory_audits``      操作审计（不落原文）
- ``agent_memory_outbox``      向量投影待办（可靠同步 / 可重试 / 可重建）
- ``agent_session_summaries``  会话摘要

不做外键：记忆生命周期由服务层保证，且与业务流程解耦（便于独立清理与重建）。
兼容性：``MEMORY_ENABLED`` 默认关闭，未启用新能力时业务行为不变。
回滚：``downgrade()`` 会丢弃全部记忆数据，执行前必须备份。
"""
from alembic import op
import sqlalchemy as sa

revision = "20261108_30"
down_revision = "20261027_29"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "agent_memories",
        sa.Column("memory_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("memory_type", sa.String(40), nullable=False),
        sa.Column("memory_key", sa.String(191)),
        sa.Column("memory_value", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_ref", sa.String(128)),
        sa.Column("source_conversation_id", sa.Integer()),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("embedding_version", sa.String(64), nullable=False),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column("expires_at", sa.DateTime()),
        sa.Column("deleted_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "project_id",
            "memory_type",
            "memory_key",
            name="uq_agent_memories_idempotency",
        ),
    )
    op.create_index("ix_agent_memories_user_id", "agent_memories", ["user_id"])
    op.create_index(
        "ix_agent_memories_scope", "agent_memories", ["tenant_id", "user_id", "project_id", "status"]
    )
    op.create_index("ix_agent_memories_expires", "agent_memories", ["expires_at"])

    op.create_table(
        "agent_memory_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("memory_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("memory_value", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("created_by", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("memory_id", "version", name="uq_agent_memory_versions_memory_version"),
    )
    op.create_index("ix_agent_memory_versions_memory_id", "agent_memory_versions", ["memory_id"])

    op.create_table(
        "agent_memory_audits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("memory_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("actor_user_id", sa.Integer()),
        sa.Column("before_json", sa.JSON()),
        sa.Column("after_json", sa.JSON()),
        sa.Column("reason", sa.String(255)),
        sa.Column("trace_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_agent_memory_audits_memory", "agent_memory_audits", ["memory_id", "created_at"]
    )
    op.create_index(
        "ix_agent_memory_audits_actor", "agent_memory_audits", ["actor_user_id", "created_at"]
    )

    op.create_table(
        "agent_memory_outbox",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("memory_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("embedding_version", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("payload_json", sa.JSON()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(500)),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_agent_memory_outbox_status", "agent_memory_outbox", ["status", "available_at"]
    )
    op.create_index("ix_agent_memory_outbox_memory", "agent_memory_outbox", ["memory_id"])

    op.create_table(
        "agent_session_summaries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("memory_id", sa.String(36)),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "project_id", "session_id", name="uq_agent_session_summaries_session"
        ),
    )
    op.create_index(
        "ix_agent_session_summaries_user",
        "agent_session_summaries",
        ["tenant_id", "user_id", "project_id"],
    )


def downgrade():
    op.drop_index("ix_agent_session_summaries_user", table_name="agent_session_summaries")
    op.drop_table("agent_session_summaries")
    op.drop_index("ix_agent_memory_outbox_memory", table_name="agent_memory_outbox")
    op.drop_index("ix_agent_memory_outbox_status", table_name="agent_memory_outbox")
    op.drop_table("agent_memory_outbox")
    op.drop_index("ix_agent_memory_audits_actor", table_name="agent_memory_audits")
    op.drop_index("ix_agent_memory_audits_memory", table_name="agent_memory_audits")
    op.drop_table("agent_memory_audits")
    op.drop_index("ix_agent_memory_versions_memory_id", table_name="agent_memory_versions")
    op.drop_table("agent_memory_versions")
    op.drop_index("ix_agent_memories_expires", table_name="agent_memories")
    op.drop_index("ix_agent_memories_scope", table_name="agent_memories")
    op.drop_index("ix_agent_memories_user_id", table_name="agent_memories")
    op.drop_table("agent_memories")
