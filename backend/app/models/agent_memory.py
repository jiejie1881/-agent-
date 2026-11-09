"""长期记忆权威模型（MySQL 为权威存储，Chroma 为可重建的派生索引）。

设计要点：
- ``agent_memories`` 保存记忆本体（软删除、过期、版本号）；
- ``agent_memory_versions`` 保存每次写入的历史快照；
- ``agent_memory_audits`` 保存操作审计（不落记忆原文，只落摘要）；
- ``agent_memory_outbox`` 保存向量投影待办（可靠同步、可重试、可重建）；
- ``agent_session_summaries`` 保存会话摘要及其关联的记忆。

历史兼容：``AgentUserMemory`` 作为本模块 ``AgentMemory`` 的别名保留。
原 ``agent_user_memories`` 草稿表从未在真实库执行（alembic_version=20261027_29，
库内无该表），本次迁移将其替换为规范表名，见
``alembic/versions/20261108_30_agent_memory.py``。
"""
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base

MEMORY_STATUS_PENDING = "PENDING"
MEMORY_STATUS_ACTIVE = "ACTIVE"
MEMORY_STATUS_ARCHIVED = "ARCHIVED"
MEMORY_STATUS_DELETED = "DELETED"


class AgentMemory(Base):
    """长期记忆本体。"""

    __tablename__ = "agent_memories"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "project_id",
            "memory_type",
            "memory_key",
            name="uq_agent_memories_idempotency",
        ),
        Index("ix_agent_memories_scope", "tenant_id", "user_id", "project_id", "status"),
        Index("ix_agent_memories_expires", "expires_at"),
    )

    memory_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    memory_type: Mapped[str] = mapped_column(String(40), nullable=False)
    memory_key: Mapped[str | None] = mapped_column(String(191))
    memory_value: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="user_explicit")
    source_ref: Mapped[str | None] = mapped_column(String(128))
    source_conversation_id: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=MEMORY_STATUS_PENDING)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    embedding_version: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    # ---- 向后兼容的只读视图（旧调用方按 content/embedding_id 读取）----
    @property
    def content(self) -> str:
        return self.memory_value

    @property
    def embedding_id(self) -> str:
        return self.memory_id


class AgentMemoryVersion(Base):
    """记忆版本快照（每次写入 version +1）。"""

    __tablename__ = "agent_memory_versions"
    __table_args__ = (
        UniqueConstraint("memory_id", "version", name="uq_agent_memory_versions_memory_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    memory_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_value: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class AgentMemoryAudit(Base):
    """记忆操作审计（只保存摘要哈希与长度，不保存记忆原文）。"""

    __tablename__ = "agent_memory_audits"
    __table_args__ = (
        Index("ix_agent_memory_audits_memory", "memory_id", "created_at"),
        Index("ix_agent_memory_audits_actor", "actor_user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    memory_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(Integer)
    before_json: Mapped[dict | None] = mapped_column(JSON)
    after_json: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(String(255))
    trace_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class AgentMemoryOutbox(Base):
    """向量投影待办（Outbox 模式：可靠同步、幂等、可重试、可重建）。"""

    __tablename__ = "agent_memory_outbox"
    __table_args__ = (
        Index("ix_agent_memory_outbox_status", "status", "available_at"),
        Index("ix_agent_memory_outbox_memory", "memory_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    memory_id: Mapped[str] = mapped_column(String(36), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    payload_json: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    available_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class AgentSessionSummary(Base):
    """会话摘要（跨会话长期记忆的入口之一）。"""

    __tablename__ = "agent_session_summaries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "session_id", name="uq_agent_session_summaries_session"),
        Index("ix_agent_session_summaries_user", "tenant_id", "user_id", "project_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="agent_session")
    memory_id: Mapped[str | None] = mapped_column(String(36))
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


# 历史别名：保留原草稿模型名，避免既有导入失效
AgentUserMemory = AgentMemory
