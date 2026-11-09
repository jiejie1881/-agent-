"""Offline governance API: existing authentication, per-object ACL, no live models."""
from collections import Counter
import statistics
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.routing import APIRoute
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from app.api.auth_dependencies import CurrentUser
from app.api.dependencies import DbSession
from app.core.config import get_settings
from app.domain.exceptions import BusinessError, NotFoundError
from app.models.audit_log import AuditLog
from app.models.knowledge import (KnowledgeChunkRecord, KnowledgeDocumentVersion,
                                  KnowledgeEvaluationRun, KnowledgeIndexVersion, KnowledgeJob)
from app.schemas.knowledge import (KnowledgeBaseInput, KnowledgeBaseUpdate, KnowledgeBuildInput,
    KnowledgeDeleteInput, KnowledgeDocumentAclInput, KnowledgePublishInput, KnowledgeQueryInput, KnowledgeValidationInput)
from app.services.knowledge_job_service import KnowledgeJobService
from app.services.knowledge_management_service import KnowledgeManagementService, MAX_UPLOAD
from app.services.knowledge_retrieval_service import KnowledgeRetrievalService
from app.services.knowledge_job_status import JOB_EVENTS, describe_job
from app.services.knowledge_execution import require_knowledge_execution


def offline_surface(db: DbSession):
    config = get_settings()
    if not config.rag_governance_enabled:
        raise NotFoundError("知识治理入口未启用")
    offline = config.rag_governance_offline_enabled and config.app_environment == 'test'
    # Preserve the existing error contract for non-production unapproved use.
    if not offline and config.app_environment != 'production':
        raise BusinessError("本阶段仅授权隔离SQLite离线验收", 503, "KNOWLEDGE_OFFLINE_ONLY")
    require_knowledge_execution(db, offline)
    return config


class BoundedKnowledgeRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def bounded(request: Request):
            limit = MAX_UPLOAD + 65536  # Bounded multipart overhead in addition to file size.
            try:
                length = int(request.headers.get("content-length", "0"))
            except ValueError:
                raise BusinessError("请求长度无效", 400) from None
            if length < 0 or length > limit:
                raise BusinessError("知识管理请求过大", 413)
            total = 0

            async def receive():
                nonlocal total
                message = await request.receive()
                total += len(message.get("body", b""))
                if total > limit:
                    raise BusinessError("知识管理请求过大", 413)
                return message

            return await original(Request(request.scope, receive=receive))
        return bounded


router = APIRouter(prefix="/knowledge", tags=["knowledge-governance"], dependencies=[Depends(offline_surface)], route_class=BoundedKnowledgeRoute)


def require_knowledge_admin(db: DbSession, actor: CurrentUser):
    manager(db).admin(actor)
    return actor


Admin = Annotated[object, Depends(require_knowledge_admin)]


def manager(db):
    config = get_settings()
    return KnowledgeManagementService(db, config.rag_governance_root,
        offline=config.rag_governance_offline_enabled and config.app_environment == 'test')


def jobs(db):
    config = get_settings()
    return KnowledgeJobService(db, config.rag_governance_root,
        offline=config.rag_governance_offline_enabled and config.app_environment == 'test')


def retrieval(db):
    config = get_settings()
    return KnowledgeRetrievalService(db, config.rag_governance_root,
        offline=config.rag_governance_offline_enabled and config.app_environment == 'test',
        default_base_id=config.rag_governance_default_base_id, default_strategy=config.rag_retrieval_mode, settings=config)


FIELDS = {
    "KnowledgeBase": "id name business_scope status visibility read_roles active_index_id revision running_job_id created_at",
    "KnowledgeDocument": "id base_id title current_version_id revision deleted visibility read_roles created_at",
    "KnowledgeDocumentVersion": "id document_id version sha256 original_name source_label stage error_type created_at",
    "KnowledgeJob": "id base_id actor_id status stage attempts max_attempts retryable error_type result_index_id duration_ms model_calls cost created_at",
    "KnowledgeIndexVersion": "id base_id job_id version snapshot embedding_model model_revision dimension configuration status validation_kind published_at created_at",
    "KnowledgeEvaluationRun": "id index_id dataset dataset_sha256 status metrics cases created_at",
    "AuditLog": "id username action object_type object_id changes created_at",
}


def view(value):
    return {name: getattr(value, name) for name in FIELDS[type(value).__name__].split()}


def job_views(db, values):
    values = list(values)
    if not values:
        return []
    events = list(db.scalars(select(AuditLog).where(
        AuditLog.object_type == "KnowledgeJob", AuditLog.object_id.in_([job.id for job in values]),
        AuditLog.action.in_(JOB_EVENTS)).order_by(AuditLog.id.desc()).limit(3000)))
    by_job = {job.id: [] for job in values}
    for event in events:
        by_job[event.object_id].append(event)
    return [{**view(job), **describe_job(job, by_job[job.id])} for job in values]


@router.get("/bases")
def list_bases(db: DbSession, actor: CurrentUser):
    return [view(b) for b in manager(db).list_bases(actor)]


@router.post("/bases")
def create_base(data: KnowledgeBaseInput, db: DbSession, actor: Admin):
    return view(manager(db).create_base(actor, data))


@router.patch("/bases/{base_id}")
def update_base(base_id: int, data: KnowledgeBaseUpdate, db: DbSession, actor: Admin):
    return view(manager(db).update_base(actor, base_id, data))


@router.get("/bases/{base_id}/documents")
def documents(base_id: int, db: DbSession, actor: Admin):
    return [view(d) for d in manager(db).documents(actor, base_id)]


@router.post("/bases/{base_id}/documents")
async def upload(base_id: int, db: DbSession, actor: Admin, file: UploadFile = File(...),
                 source_label: str = Form(default="upload", max_length=300),
                 expected_revision: int | None = Form(default=None, ge=0), document_id: int | None = Form(default=None, gt=0)):
    service = manager(db)
    service.base(base_id, actor, write=True)
    raw = await file.read(MAX_UPLOAD + 1)
    return view(service.upload(actor, base_id, file.filename or "", raw, source_label=source_label,
                              expected_revision=expected_revision, document_id=document_id))


@router.get("/documents/{document_id}/versions")
def versions(document_id: int, db: DbSession, actor: Admin):
    return [view(v) for v in manager(db).versions(actor, document_id)]


@router.get("/documents/{document_id}/versions/{version_id}/content")
def content(document_id: int, version_id: int, db: DbSession, actor: Admin):
    service = manager(db)
    service.document(actor, document_id)
    version = db.get(KnowledgeDocumentVersion, version_id)
    if version is None or version.document_id != document_id:
        raise NotFoundError("文档版本不存在")
    return PlainTextResponse(service.read_version(version), headers={"X-Content-Type-Options": "nosniff"})


@router.patch("/documents/{document_id}/permissions")
def permissions(document_id: int, data: KnowledgeDocumentAclInput, db: DbSession, actor: Admin):
    return view(manager(db).update_document_acl(actor, document_id, data))


@router.delete("/documents/{document_id}")
def delete_document(document_id: int, data: KnowledgeDeleteInput, db: DbSession, actor: Admin):
    return view(manager(db).delete_document(actor, document_id, data.expected_revision, data.confirmed))


@router.post("/bases/{base_id}/jobs")
def create_job(base_id: int, data: KnowledgeBuildInput, db: DbSession, actor: Admin):
    return job_views(db, [jobs(db).create(actor, base_id, data.idempotency_key)])[0]


@router.get("/bases/{base_id}/jobs")
def list_jobs(base_id: int, db: DbSession, actor: Admin, offset: int = Query(0, ge=0)):
    manager(db).base(base_id, actor, write=True)
    return job_views(db, db.scalars(select(KnowledgeJob).where(KnowledgeJob.base_id == base_id).order_by(
        KnowledgeJob.id.desc()).offset(offset).limit(100)))


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: DbSession, actor: Admin):
    return job_views(db, [jobs(db).get(actor, job_id)])[0]


@router.post("/jobs/{job_id}/run")
def run_job(job_id: int, db: DbSession, actor: Admin):
    return job_views(db, [jobs(db).run(actor, job_id)])[0]


@router.post("/jobs/{job_id}/retry")
def retry(job_id: int, db: DbSession, actor: Admin):
    return job_views(db, [jobs(db).retry(actor, job_id)])[0]


@router.post("/jobs/{job_id}/recover")
def recover(job_id: int, db: DbSession, actor: Admin):
    return job_views(db, [jobs(db).recover_expired(actor, job_id)])[0]


@router.get("/bases/{base_id}/indexes")
def indexes(base_id: int, db: DbSession, actor: Admin):
    manager(db).base(base_id, actor, write=True)
    return [view(i) for i in db.scalars(select(KnowledgeIndexVersion).where(
        KnowledgeIndexVersion.base_id == base_id).order_by(KnowledgeIndexVersion.id.desc()).limit(100))]


@router.get("/indexes/{index_id}/chunks")
def chunks(index_id: int, db: DbSession, actor: CurrentUser, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    service = retrieval(db)
    value = service.management.index(actor, index_id)
    base = service.management.base(value.base_id, actor)
    if actor.role.value != "ADMIN" and (base.active_index_id != value.id or value.status != "PUBLISHED"):
        raise NotFoundError("索引不存在或尚未发布")
    service.jobs.checked_index(value)
    allowed = service._allowed(actor, value.base_id, value.id)
    query = select(KnowledgeChunkRecord).where(KnowledgeChunkRecord.index_id == index_id,
        KnowledgeChunkRecord.chunk_id.in_(allowed)).order_by(KnowledgeChunkRecord.id).offset(offset).limit(limit)
    records = list(db.scalars(query))
    return {"index_id": value.id, "index_version": value.version, "configuration": value.configuration,
            "total_chunks": len(allowed), "offset": offset, "limit": limit,
            "page_characters": sum(len(c.content) for c in records),
            "chunks": [{"chunk_id": c.chunk_id, "document_version_id": c.document_version_id,
                        "content": c.content, "char_count": len(c.content), "metadata": c.metadata_json} for c in records]}


@router.get("/indexes/{index_id}/diff")
def differences(index_id: int, db: DbSession, actor: Admin):
    service = manager(db)
    value = service.index(actor, index_id, write=True)
    base = service.base(value.base_id, actor, write=True)
    old = db.get(KnowledgeIndexVersion, base.active_index_id) if base.active_index_id else None
    before, after = old.snapshot if old else {}, value.snapshot
    return {"active_index_id": base.active_index_id, "candidate_index_id": value.id,
        "added_documents": sorted(set(after) - set(before)), "removed_documents": sorted(set(before) - set(after)),
        "updated_documents": sorted(k for k in set(before) & set(after) if before[k] != after[k]),
        "model_changed": bool(old and (old.model_revision != value.model_revision or old.dimension != value.dimension)),
        "quality_status": value.status, "publication_is_separate": True}


@router.post("/indexes/{index_id}/validate")
def validate(index_id: int, data: KnowledgeValidationInput, db: DbSession, actor: Admin):
    value = jobs(db).validate(actor, index_id) if data.dataset == "document_smoke" else retrieval(db).evaluate(
        actor, index_id, data.dataset, data.strategy)
    return view(value)


@router.post("/indexes/{index_id}/publish")
def publish(index_id: int, data: KnowledgePublishInput, db: DbSession, actor: Admin):
    return view(manager(db).publish(actor, index_id, data.expected_active_id, data.expected_revision, data.confirmed))


@router.post("/indexes/{index_id}/rollback")
def rollback(index_id: int, data: KnowledgePublishInput, db: DbSession, actor: Admin):
    return view(manager(db).publish(actor, index_id, data.expected_active_id, data.expected_revision, data.confirmed, rollback=True))


@router.delete("/indexes/{index_id}")
def retire(index_id: int, data: KnowledgeDeleteInput, db: DbSession, actor: Admin):
    return view(manager(db).retire_index(actor, index_id, data.expected_revision, data.confirmed))


@router.post("/retrieval/preview")
def laboratory(data: KnowledgeQueryInput, db: DbSession, actor: CurrentUser):
    service = retrieval(db)
    values = service.search_for_actor(actor, data.query, data.top_k, data.document_type, base_id=data.base_id,
        strategy=data.strategy, index_id=data.index_id)
    return {"results": [v.model_dump() for v in values], "candidates": [v.model_dump() for v in service.last_candidates],
        "stats": service.last_search_stats, "evidence_status": "CANDIDATES_UNVERIFIED" if values else "NO_EVIDENCE",
        "answerability": "NOT_EVALUATED", "refusal_reason": None if values else "没有匹配的授权证据；不生成答案",
        "generation": "NOT RUN", "scope": "OFFLINE_SYNTHETIC_NOT_SEMANTIC" if service.offline else "REAL_EMBEDDING_NOT_BLIND"}


@router.get("/bases/{base_id}/evaluations")
def evaluations(base_id: int, db: DbSession, actor: Admin):
    manager(db).base(base_id, actor, write=True)
    return [view(x) for x in db.scalars(select(KnowledgeEvaluationRun).join(KnowledgeIndexVersion,
        KnowledgeEvaluationRun.index_id == KnowledgeIndexVersion.id).where(KnowledgeIndexVersion.base_id == base_id).order_by(
            KnowledgeEvaluationRun.id.desc()).limit(100))]


@router.get("/metrics")
def metrics(db: DbSession, actor: Admin):
    manager(db).admin(actor)
    tasks = list(db.scalars(select(KnowledgeJob).order_by(KnowledgeJob.id.desc()).limit(1000)))
    events = list(db.scalars(select(AuditLog).where(AuditLog.action.in_(["RAG_SEARCHED", "RAG_SEARCH_FAILED"])).order_by(
        AuditLog.id.desc()).limit(1000)))
    latencies = [float((e.changes or {}).get("duration_ms", 0)) for e in events]
    config = get_settings()
    offline = config.rag_governance_offline_enabled and config.app_environment == 'test'
    return {"scope": "LOCAL_OFFLINE_SYNTHETIC_LAST_1000" if offline else "GOVERNED_RUNTIME_LAST_1000", "job_statuses": dict(Counter(t.status for t in tasks)),
        "retrieval_count": len(events), "retrieval_error_rate": sum(e.action == "RAG_SEARCH_FAILED" for e in events) / len(events) if events else None,
        "retrieval_p50_ms": statistics.median(latencies) if latencies else None,
        "synthetic_embedding_calls": sum(t.model_calls or 0 for t in tasks) if offline else None,
        "document_embedding_batches": None if offline else sum(t.model_calls or 0 for t in tasks),
        "real_model_calls": None, "actual_cost": None,
        "cost_status": "UNKNOWN_REAL_MODELS_NOT_RUN" if offline else "UNKNOWN_PROVIDER_INVOICE_NOT_OBSERVED",
        "model_egress_enabled": config.model_budget_enabled}


@router.get("/audits")
def audits(db: DbSession, actor: Admin, offset: int = Query(0, ge=0)):
    manager(db).admin(actor)
    return [view(x) for x in db.scalars(select(AuditLog).where(AuditLog.action.like("RAG\\_%", escape="\\")).order_by(
        AuditLog.id.desc()).offset(offset).limit(100))]
