"""Knowledge governance metadata; immutable versions, explicit publication."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class KnowledgeBase(Base):
    __tablename__ = "rag_knowledge_bases"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    business_scope: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    visibility: Mapped[str] = mapped_column(String(20), default="ADMIN")
    read_roles: Mapped[list] = mapped_column(JSON, default=list)
    active_index_id: Mapped[int | None] = mapped_column(nullable=True)
    running_job_id: Mapped[int | None] = mapped_column(nullable=True)
    revision: Mapped[int] = mapped_column(default=0)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    __table_args__ = (CheckConstraint("status IN ('ACTIVE','ARCHIVED')", name="ck_rag_base_status"),
                      CheckConstraint("visibility IN ('PUBLIC','ROLES','ADMIN')", name="ck_rag_base_visibility"))


class KnowledgeDocument(Base):
    __tablename__ = "rag_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    base_id: Mapped[int] = mapped_column(ForeignKey("rag_knowledge_bases.id", ondelete="RESTRICT"), index=True)
    key: Mapped[str] = mapped_column(String(180))
    title: Mapped[str] = mapped_column(String(180))
    current_version_id: Mapped[int | None] = mapped_column(nullable=True)
    revision: Mapped[int] = mapped_column(default=0)
    deleted: Mapped[bool] = mapped_column(Boolean(), default=False)
    visibility: Mapped[str] = mapped_column(String(20), default="INHERIT")
    read_roles: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    __table_args__ = (UniqueConstraint("base_id", "key", name="uq_rag_document_key"),)


class KnowledgeDocumentVersion(Base):
    __tablename__ = "rag_document_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("rag_documents.id", ondelete="RESTRICT"), index=True)
    version: Mapped[int] = mapped_column()
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(160))
    original_name: Mapped[str] = mapped_column(String(180))
    source_label: Mapped[str] = mapped_column(String(300), default="upload")
    stage: Mapped[str] = mapped_column(String(24), default="UPLOADED")
    error_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    __table_args__ = (UniqueConstraint("document_id", "version", name="uq_rag_document_version"),)


class KnowledgeJob(Base):
    __tablename__ = "rag_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    base_id: Mapped[int] = mapped_column(ForeignKey("rag_knowledge_bases.id", ondelete="RESTRICT"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_sha256: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="QUEUED")
    stage: Mapped[str] = mapped_column(String(24), default="UPLOADED")
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=2)
    lease_token: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean(), default=False)
    error_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    result_index_id: Mapped[int | None] = mapped_column(nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(nullable=True)
    model_calls: Mapped[int | None] = mapped_column(nullable=True)
    cost: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    __table_args__ = (UniqueConstraint("base_id", "idempotency_key", name="uq_rag_job_key"),
                      CheckConstraint("attempts >= 0 AND max_attempts BETWEEN 1 AND 3", name="ck_rag_job_attempts"))


class KnowledgeIndexVersion(Base):
    __tablename__ = "rag_index_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    base_id: Mapped[int] = mapped_column(ForeignKey("rag_knowledge_bases.id", ondelete="RESTRICT"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("rag_jobs.id", ondelete="RESTRICT"), unique=True)
    version: Mapped[str] = mapped_column(String(32), unique=True)
    snapshot: Mapped[dict] = mapped_column(JSON)
    manifest_key: Mapped[str] = mapped_column(String(200))
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    embedding_model: Mapped[str] = mapped_column(String(120))
    model_revision: Mapped[str] = mapped_column(String(100))
    dimension: Mapped[int] = mapped_column()
    configuration: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="CANDIDATE")
    validation_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class KnowledgeChunkRecord(Base):
    __tablename__ = "rag_chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    index_id: Mapped[int] = mapped_column(ForeignKey("rag_index_versions.id", ondelete="RESTRICT"), index=True)
    document_version_id: Mapped[int] = mapped_column(ForeignKey("rag_document_versions.id", ondelete="RESTRICT"))
    chunk_id: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text())
    metadata_json: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("index_id", "chunk_id", name="uq_rag_chunk_identity"),)


class KnowledgeEvaluationRun(Base):
    __tablename__ = "rag_evaluation_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    index_id: Mapped[int] = mapped_column(ForeignKey("rag_index_versions.id", ondelete="RESTRICT"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    dataset: Mapped[str] = mapped_column(String(100))
    dataset_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))
    metrics: Mapped[dict] = mapped_column(JSON)
    cases: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
