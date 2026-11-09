"""Bounded database jobs with immutable indexes; real model execution denied."""
from datetime import timedelta
import hashlib
import inspect
from pathlib import Path
import time
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError

from app.domain.exceptions import BusinessError, ConflictError
from app.models.knowledge import (KnowledgeBase, KnowledgeChunkRecord, KnowledgeDocument,
                                  KnowledgeDocumentVersion, KnowledgeEvaluationRun,
                                  KnowledgeIndexVersion, KnowledgeJob, utcnow)
from app.rag.document_loader import DOCUMENT_TYPES, KnowledgeDocumentLoader
from app.rag.evaluation import DeterministicHashEmbedding, EvalCase, aggregate
from app.rag.rag_service import RagService
from app.rag.schemas import KnowledgeSection
from app.rag.vector_store import ChromaVectorStore
from app.rag.versioned_index import VersionedIndex, digest
from app.services.knowledge_management_service import KnowledgeManagementService, fingerprint
from app.services.knowledge_execution import require_knowledge_execution

MODEL_NAME = "OFFLINE_HASH_192_NOT_SEMANTIC"


class KnowledgeJobService:
    def __init__(self, session, storage_root, *, offline=False, timeout=15):
        if not 0 < timeout <= 60:
            raise ValueError("Job timeout must be in (0, 60]")
        self.session, self.root, self.offline, self.timeout = session, Path(storage_root), offline, timeout
        from app.core.config import get_settings
        self.settings = get_settings()
        self.management = KnowledgeManagementService(session, storage_root, offline=offline)
        self.root = self.management.root

    def _offline_gate(self):
        require_knowledge_execution(self.session, self.offline)

    def embedding(self, operation_id=None):
        if self.offline:
            return DeterministicHashEmbedding()
        from app.rag.embedding_client import OpenAICompatibleEmbeddingClient
        return OpenAICompatibleEmbeddingClient(self.settings, operation_id=operation_id)

    def identity(self):
        if self.offline:
            return MODEL_NAME, self.model_revision()
        if self.settings.app_environment != 'production':
            # Preserve metadata-only queue creation in unapproved environments.
            # run/validate/publish still fail at the execution gate before I/O.
            return 'UNAUTHORIZED_MODEL_NOT_RESOLVED', 'NO_EXECUTION_AUTHORIZATION'
        # A provider alias is not a weights revision. Record a configuration
        # fingerprint honestly; actual vector dimensions are checked separately.
        client = self.embedding()
        model, _key, endpoint = client._validated_configuration()
        return model, fingerprint({'provider': self.settings.rag_embedding_provider,
            'model': model, 'endpoint_sha256': digest(endpoint)})

    def validation_kind(self):
        return 'OFFLINE_SYNTHETIC' if self.offline else 'REAL_MODEL_DOCUMENT_SMOKE'

    def scope(self):
        return 'OFFLINE_SYNTHETIC' if self.offline else 'REAL_EMBEDDING_DOCUMENT_SMOKE_NOT_BLIND'

    @staticmethod
    def model_revision():
        return hashlib.sha256(inspect.getsource(DeterministicHashEmbedding).encode()).hexdigest()

    def create(self, actor, base_id, key):
        base = self.management.base(base_id, actor, write=True)
        if base.status != "ACTIVE" or not 8 <= len(key) <= 100:
            raise BusinessError("知识库状态或幂等键无效", 422)
        snapshot = self.management.snapshot(base_id)
        if not snapshot or len(snapshot) > 50:
            raise BusinessError("构建需要1到50份未删除文档", 422)
        model, revision = self.identity()
        request = {"documents": snapshot, "model": model, "revision": revision,
                   "chunk_size": 800, "chunk_overlap": 120}
        checksum = fingerprint(request)
        previous = self.session.scalar(select(KnowledgeJob).where(KnowledgeJob.base_id == base_id, KnowledgeJob.idempotency_key == key))
        if previous:
            if previous.request_sha256 != checksum or previous.actor_id != actor.id:
                raise ConflictError("幂等键对应不同请求")
            return previous
        try:
            job = KnowledgeJob(base_id=base_id, actor_id=actor.id, idempotency_key=key,
                               request_sha256=checksum, snapshot=request, model_calls=0,
                               cost="NOT_BILLED_SYNTHETIC" if self.offline else "PROVIDER_INVOICE_NOT_OBSERVED")
            self.session.add(job)
            self.session.flush()
            self.management.audit(actor, "RAG_JOB_CREATED", "KnowledgeJob", job.id,
                                  {"result": "QUEUED", "snapshot_sha256": checksum, "scope": self.scope()})
            self.session.commit()
            return job
        except IntegrityError:
            self.session.rollback()
            previous = self.session.scalar(select(KnowledgeJob).where(KnowledgeJob.base_id == base_id, KnowledgeJob.idempotency_key == key))
            if previous and previous.request_sha256 == checksum and previous.actor_id == actor.id:
                return previous
            raise ConflictError("构建请求并发冲突") from None
        except Exception:
            self.session.rollback()
            raise

    def get(self, actor, job_id):
        job = self.session.get(KnowledgeJob, job_id)
        if job is None:
            raise BusinessError("构建任务不存在", 404)
        self.management.base(job.base_id, actor, write=True)
        return job

    def retry(self, actor, job_id):
        job = self.get(actor, job_id)
        result = self.session.execute(update(KnowledgeJob).where(
            KnowledgeJob.id == job.id, KnowledgeJob.status == "FAILED", KnowledgeJob.retryable.is_(True),
            KnowledgeJob.attempts < KnowledgeJob.max_attempts).values(status="QUEUED", retryable=False),
            execution_options={"synchronize_session": False})
        if result.rowcount != 1:
            self.session.rollback()
            raise ConflictError("任务不可重试或已达安全次数上限")
        self.management.audit(actor, "RAG_JOB_RETRIED", "KnowledgeJob", job.id, {"result": "QUEUED"})
        self.session.commit()
        self.session.refresh(job)
        return job

    def recover_expired(self, actor, job_id):
        job = self.get(actor, job_id)
        if job.status != "RUNNING" or job.lease_until is None or job.lease_until > utcnow():
            raise ConflictError("任务仍有有效租约或不在运行")
        result = self.session.execute(update(KnowledgeJob).where(KnowledgeJob.id == job.id,
            KnowledgeJob.status == "RUNNING", KnowledgeJob.lease_until <= utcnow()).values(
                status="FAILED", error_type="LEASE_EXPIRED", retryable=job.stage != "EMBEDDING", lease_token=None),
            execution_options={"synchronize_session": False})
        if result.rowcount != 1:
            self.session.rollback()
            raise ConflictError("任务租约已变化")
        self.session.execute(update(KnowledgeBase).where(KnowledgeBase.id == job.base_id,
            KnowledgeBase.running_job_id == job.id).values(running_job_id=None))
        self.management.audit(actor, "RAG_JOB_FAILED", "KnowledgeJob", job.id,
            {"result": "FAILED", "stage": job.stage, "error_type": "LEASE_EXPIRED"})
        self.session.commit()
        self.session.refresh(job)
        return job

    def _stage(self, actor, job, token, stage, deadline):
        if time.monotonic() > deadline:
            raise TimeoutError("Knowledge job deadline exceeded")
        result = self.session.execute(update(KnowledgeJob).where(KnowledgeJob.id == job.id,
            KnowledgeJob.status == "RUNNING", KnowledgeJob.lease_token == token,
            KnowledgeJob.lease_until > utcnow()).values(stage=stage), execution_options={"synchronize_session": False})
        if result.rowcount != 1:
            self.session.refresh(job)
            if job.status == "RUNNING" and job.lease_token == token and job.lease_until and job.lease_until <= utcnow():
                raise TimeoutError("Knowledge job lease expired")
            raise ConflictError("任务租约失效")
        for version_id in job.snapshot["documents"].values():
            version = self.session.get(KnowledgeDocumentVersion, version_id)
            if version:
                version.stage, version.error_type = stage, None
        self.management.audit(actor, "RAG_JOB_STAGE", "KnowledgeJob", job.id,
                              {"result": "RUNNING", "stage": stage, "attempt": job.attempts})
        self.session.commit()
        self.session.refresh(job)

    def _sections(self, job):
        loader, sections = KnowledgeDocumentLoader(), []
        for doc_id, version_id in job.snapshot["documents"].items():
            version = self.session.get(KnowledgeDocumentVersion, version_id)
            doc = self.session.get(KnowledgeDocument, int(doc_id))
            if version is None or doc is None or version.document_id != doc.id or doc.base_id != job.base_id:
                raise ConflictError("任务文档快照不一致")
            text = loader._clean(self.management.read_version(version))
            # A replacement may change extension/name; parse the frozen version,
            # not the document's original display title.
            path = Path(version.original_name)
            document_type = DOCUMENT_TYPES.get(path.stem, 'system_manual')
            parts = ([loader._section(path, document_type, '正文', text)] if path.suffix.lower() == '.txt'
                     else loader._markdown_sections(path, document_type, text))
            sections.extend(p.model_copy(update={"document_id": f"kb:{job.base_id}:doc:{doc.id}:version:{version.id}"}) for p in parts)
        return sections

    def run(self, actor, job_id):
        job = self.get(actor, job_id)
        if job.status == "SUCCEEDED":
            return job
        self._offline_gate()
        token, started = uuid4().hex, time.monotonic()
        deadline = started + self.timeout
        try:
            claim = self.session.execute(update(KnowledgeJob).where(KnowledgeJob.id == job.id,
                KnowledgeJob.status == "QUEUED", KnowledgeJob.attempts < KnowledgeJob.max_attempts).values(
                    status="RUNNING", attempts=KnowledgeJob.attempts + 1, lease_token=token,
                    lease_until=utcnow() + timedelta(seconds=self.timeout), error_type=None),
                execution_options={"synchronize_session": False})
            busy = self.session.execute(update(KnowledgeBase).where(KnowledgeBase.id == job.base_id,
                KnowledgeBase.status == "ACTIVE", KnowledgeBase.running_job_id.is_(None)).values(running_job_id=job.id))
            if claim.rowcount != 1 or busy.rowcount != 1:
                raise ConflictError("任务已被领取或知识库已有运行任务")
            self.session.refresh(job)
            self.management.audit(actor, "RAG_JOB_STARTED", "KnowledgeJob", job.id,
                                  {"result": "RUNNING", "attempt": job.attempts})
            self.session.commit()
            self.session.refresh(job)
        except Exception:
            self.session.rollback()
            raise
        try:
            self._stage(actor, job, token, "PARSING", deadline)
            sections = self._sections(job)
            self._stage(actor, job, token, "CHUNKING", deadline)
            folder = self.management.path(f"builds/job-{job.id}-attempt-{job.attempts}")
            folder.mkdir(parents=True, exist_ok=False)
            corpus = folder / "corpus"
            corpus.mkdir()
            for number, section in enumerate(sections):
                (corpus / f"section-{number}.txt").write_text(section.content, encoding="utf-8")
            service = RagService(self.embedding(f'knowledge-job:{job.id}:attempt:{job.attempts}'), ChromaVectorStore(folder / "chroma", f"kb_{job.base_id}"),
                knowledge_base_dir=str(corpus), retrieval_mode="vector", chunk_size=800, chunk_overlap=120)
            chunks = service.splitter.split(sections)
            chunks = [c.model_copy(update={"chunk_id": digest(c.model_dump(exclude={"chunk_id"}))}) for c in chunks]
            if not 1 <= len(chunks) <= 1000:
                raise BusinessError("离线构建仅允许1到1000个Chunk", 422)
            self._stage(actor, job, token, "EMBEDDING", deadline)
            job.model_calls = 1
            self.session.commit()
            embeddings = service.embedding_client.embed_documents([c.content for c in chunks])
            self._stage(actor, job, token, "INDEXING", deadline)
            version = service.versions.publish(chunks, embeddings, service._configuration(), activate=False)
            manifest = service.versions.root / (version + ".json")
            payload, checked_chunks, store = service.versions._read(manifest)
            service.versions.validate_vector(checked_chunks, store)
            if time.monotonic() > deadline:
                raise TimeoutError("Index build exceeded deadline")
            value = KnowledgeIndexVersion(base_id=job.base_id, job_id=job.id, version=version,
                snapshot=job.snapshot["documents"], manifest_key=manifest.relative_to(self.root).as_posix(),
                manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(), embedding_model=job.snapshot['model'],
                model_revision=job.snapshot['revision'], dimension=payload["embedding_dimension"], configuration=payload["configuration"])
            self.session.add(value)
            self.session.flush()
            for c in checked_chunks:
                version_id = int(c.document_id.rsplit(":", 1)[-1])
                self.session.add(KnowledgeChunkRecord(index_id=value.id, document_version_id=version_id,
                    chunk_id=c.chunk_id, content=c.content, metadata_json=c.model_dump()))
            finish = self.session.execute(update(KnowledgeJob).where(KnowledgeJob.id == job.id,
                KnowledgeJob.status == "RUNNING", KnowledgeJob.lease_token == token,
                KnowledgeJob.lease_until > utcnow()).values(status="SUCCEEDED",
                    stage="READY", result_index_id=value.id, duration_ms=(time.monotonic() - started) * 1000,
                    lease_token=None, lease_until=None), execution_options={"synchronize_session": False})
            if finish.rowcount != 1:
                raise ConflictError("任务完成时租约已失效")
            for version_id in job.snapshot["documents"].values():
                self.session.get(KnowledgeDocumentVersion, version_id).stage = "READY"
            self.session.execute(update(KnowledgeBase).where(KnowledgeBase.id == job.base_id,
                KnowledgeBase.running_job_id == job.id).values(running_job_id=None))
            self.management.audit(actor, "RAG_JOB_COMPLETED", "KnowledgeJob", job.id,
                {"result": "SUCCEEDED", "index_id": value.id, "scope": self.scope(), "auto_publish": False,
                 "attempt": job.attempts})
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            self.session.refresh(job)
            stage = job.stage
            result = self.session.execute(update(KnowledgeJob).where(KnowledgeJob.id == job.id,
                KnowledgeJob.status == "RUNNING", KnowledgeJob.lease_token == token).values(status="FAILED",
                    error_type=type(exc).__name__[:80], retryable=isinstance(exc, (OSError, TimeoutError)) and stage != "EMBEDDING",
                    lease_token=None, lease_until=None, duration_ms=(time.monotonic() - started) * 1000),
                execution_options={"synchronize_session": False})
            if result.rowcount:
                for version_id in job.snapshot["documents"].values():
                    v = self.session.get(KnowledgeDocumentVersion, version_id)
                    v.stage, v.error_type = "FAILED", type(exc).__name__[:80]
                self.session.execute(update(KnowledgeBase).where(KnowledgeBase.id == job.base_id,
                    KnowledgeBase.running_job_id == job.id).values(running_job_id=None))
                self.management.audit(actor, "RAG_JOB_FAILED", "KnowledgeJob", job.id,
                    {"result": "FAILED", "stage": stage, "error_type": type(exc).__name__[:80], "attempt": job.attempts})
                self.session.commit()
            else:
                self.session.rollback()
        self.session.refresh(job)
        return job

    def checked_index(self, value):
        manifest = self.management.path(value.manifest_key)
        if hashlib.sha256(manifest.read_bytes()).hexdigest() != value.manifest_sha256:
            raise ConflictError("索引清单摘要不一致")
        model, revision = self.identity()
        if (value.embedding_model != model or value.model_revision != revision
                or (value.dimension != 192 if self.offline else value.dimension < 1)):
            raise ConflictError("模型版本或向量维度不兼容")
        store = ChromaVectorStore(manifest.parents[2], f"kb_{value.base_id}")
        versions = VersionedIndex(store)
        payload, chunks, checked_store = versions._read(manifest)
        if value.dimension != payload['embedding_dimension']:
            raise ConflictError('数据库与索引向量维度不兼容')
        if payload["version"] != value.version or payload["configuration"] != value.configuration:
            raise ConflictError("索引版本与数据库记录不一致")
        versions.validate_vector(chunks, checked_store)
        records = list(self.session.scalars(select(KnowledgeChunkRecord).where(KnowledgeChunkRecord.index_id == value.id)))
        if {c.chunk_id: c.model_dump() for c in chunks} != {c.chunk_id: c.metadata_json for c in records}:
            raise ConflictError("Chunk元数据与索引不一致")
        for record in records:
            version = self.session.get(KnowledgeDocumentVersion, record.document_version_id)
            document = self.session.get(KnowledgeDocument, version.document_id) if version else None
            if not document or document.base_id != value.base_id or value.snapshot.get(str(document.id)) != version.id:
                raise ConflictError("索引文档归属不一致")
            if (record.content != record.metadata_json.get("content") or
                    record.metadata_json.get("document_id") != f"kb:{value.base_id}:doc:{document.id}:version:{version.id}"):
                raise ConflictError("Chunk正文或文档版本引用不一致")
        return payload, chunks, checked_store

    def validate(self, actor, index_id, *, validator=None):
        self._offline_gate()
        value = self.management.index(actor, index_id, write=True)
        if value.status == "RETIRED":
            raise ConflictError("退役索引不能重新验证，请构建新候选")
        payload, chunks, store = self.checked_index(value)
        service = RagService(self.embedding(), store, knowledge_base_dir="unused", retrieval_mode="bm25")
        service.versions = SimpleNamespace(load=lambda: (payload, chunks, store), validate_vector=lambda *_: None)
        # New versioned source content comes from the immutable verified chunk manifest.
        service.loader = SimpleNamespace(load_directory=lambda _: [KnowledgeSection.model_validate(c.model_dump()) for c in chunks])
        cases, returned, rows = [], {}, []
        for chunk in chunks:
            case = EvalCase(chunk.chunk_id, chunk.content[:200], frozenset({chunk.chunk_id}))
            hits = service.search(case.query, top_k=10)
            ids = [h.chunk_id for h in hits]
            if len(ids) != len(set(ids)):
                raise ConflictError("评测拒绝重复结果ID")
            cases.append(case)
            returned[case.id] = ids
            rows.append({"id": case.id, "expected": [chunk.chunk_id], "returned": ids})
        metrics = aggregate(cases, returned, 10).as_dict()
        passed = all(c.id in returned[c.id] for c in cases)
        if validator is not None:
            passed = bool(validator(rows)) and passed
        from app.rag.evaluation_pipeline import Observation, evaluate_observations
        pipeline = evaluate_observations(cases, [Observation(row["id"], retrieved=tuple(row["returned"])) for row in rows],
            k=10, dataset_sha256=fingerprint([c.model_dump() for c in chunks]), corpus_version=fingerprint(value.snapshot),
            model_version=value.model_revision, strategy="bm25", scope="OFFLINE_SYNTHETIC_DOCUMENT_SMOKE_NOT_BLIND" if self.offline else self.scope())
        evaluation = KnowledgeEvaluationRun(index_id=value.id, actor_id=actor.id, dataset="document_smoke",
            dataset_sha256=fingerprint([c.model_dump() for c in chunks]), status="PASS" if passed else "FAIL",
            metrics={**metrics, "scope": "OFFLINE_SYNTHETIC_DOCUMENT_SMOKE_NOT_BLIND" if self.offline else self.scope(), "pipeline": pipeline}, cases=rows)
        return self._finish_validation(actor, value, evaluation, "RAG_INDEX_VALIDATED",
            {"scope": self.scope(), "dataset": "document_smoke"})

    def _finish_validation(self, actor, value, evaluation, action, details):
        """Commit against current SQL state, not the pre-retrieval ORM snapshot.

        A concurrent publication must stay published; retirement is terminal.
        The UPDATE locks the index until the result/audit commit, serializing
        validation outcome IDs with their index state transitions. No active
        pointer changes and no network/provider operation happen here.
        """
        self._offline_gate()
        self.management.admin(actor)
        passed = evaluation.status == "PASS"
        result = self.session.execute(update(KnowledgeIndexVersion).where(
            KnowledgeIndexVersion.id == value.id,
            KnowledgeIndexVersion.status.in_(["CANDIDATE", "VALIDATED", "PUBLISHED"])).values(
                status=case((KnowledgeIndexVersion.status == "PUBLISHED", "PUBLISHED"),
                            else_="VALIDATED" if passed else "CANDIDATE"),
                validation_kind=self.validation_kind() if passed else None),
            execution_options={"synchronize_session": False})
        if result.rowcount != 1:
            # Keep the computed result as evidence, but do not revive/validate
            # a target which was retired while retrieval was running.
            evaluation.status = "BLOCKED"
            evaluation.metrics = {**evaluation.metrics, "publication_blocker": "INDEX_STATE_CHANGED"}
        self.session.add(evaluation)
        self.management.audit(actor, action, "KnowledgeIndex", value.id,
            {**details, "result": evaluation.status})
        self.session.commit()
        self.session.refresh(value)
        return evaluation
