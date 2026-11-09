"""One authorized retrieval contract for admin laboratory and Agent tools."""
import hashlib
import math
from pathlib import Path
import time
from types import SimpleNamespace

from sqlalchemy import select
from app.core.config import get_settings

from app.domain.exceptions import BusinessError, ConflictError, NotFoundError
from app.models.knowledge import (KnowledgeBase, KnowledgeChunkRecord, KnowledgeDocument,
                                  KnowledgeDocumentVersion, KnowledgeEvaluationRun, KnowledgeIndexVersion)
from app.models.user import User
from app.rag.evaluation import (aggregate,
                               load_json_dataset, resolve_expected_cases, resolve_source_section_cases)
from app.rag.rag_service import RagService
from app.rag.schemas import KnowledgeSection
from app.rag.answerability import acceptance_gates
from app.rag.evaluation_pipeline import Observation, evaluate_observations
from app.services.knowledge_job_service import KnowledgeJobService
from app.services.knowledge_management_service import KnowledgeManagementService, fingerprint


class KnowledgeRetrievalService:
    def __init__(self, session, storage_root, *, offline=False, default_base_id=None, default_strategy=None, settings=None):
        self.session, self.root, self.offline = session, storage_root, offline
        self.settings = settings if settings is not None else get_settings()
        self.default_base_id = default_base_id if default_base_id is not None else self.settings.rag_governance_default_base_id
        self.default_strategy = default_strategy if default_strategy is not None else self.settings.rag_retrieval_mode
        self.management = KnowledgeManagementService(session, storage_root, offline=offline)
        self.jobs = KnowledgeJobService(session, storage_root, offline=offline)
        self.last_search_stats = {}
        self.last_candidates = []

    def _allowed(self, actor, base_id, index_id):
        base = self.session.scalar(select(KnowledgeBase).where(KnowledgeBase.id == base_id).execution_options(populate_existing=True))
        if not base or base.status != "ACTIVE" or not self.management.may_read(base, actor):
            raise NotFoundError("知识库不存在或无权访问")
        pairs = self.session.execute(select(KnowledgeChunkRecord.chunk_id, KnowledgeDocument).select_from(KnowledgeChunkRecord).join(
            KnowledgeDocumentVersion, KnowledgeChunkRecord.document_version_id == KnowledgeDocumentVersion.id).join(
            KnowledgeDocument, KnowledgeDocumentVersion.document_id == KnowledgeDocument.id).where(
            KnowledgeChunkRecord.index_id == index_id, KnowledgeDocument.base_id == base_id).execution_options(populate_existing=True))
        return {key for key, doc in pairs if not doc.deleted and self.management.may_read_document(base, doc, actor)}

    def prepare(self, actor, base_id, strategy, *, index_id=None):
        self.jobs._offline_gate()
        if self.offline and self.settings.rag_reranker_enabled:
            raise BusinessError('本批治理离线模式未启用真实精排，已拒绝而非静默忽略配置', 503, 'GOVERNED_RERANKER_NOT_ENABLED')
        base = self.management.base(base_id, actor)
        if base.status != "ACTIVE":
            raise ConflictError("归档知识库不能检索")
        if strategy not in {"vector", "bm25", "hybrid"}:
            raise BusinessError("检索策略无效", 422)
        if index_id is not None:
            self.management.admin(actor)
        target = index_id if index_id is not None else base.active_index_id
        value = self.session.get(KnowledgeIndexVersion, target) if target else None
        if value is None or value.base_id != base.id or value.status == "RETIRED":
            raise NotFoundError("没有可用的知识索引")
        if index_id is None and value.status != "PUBLISHED":
            raise ConflictError("活动索引状态不一致")
        payload, chunks, store = self.jobs.checked_index(value)
        from uuid import uuid4
        from app.rag.reranker import build_reranker
        operation_id = f'knowledge-query:{value.id}:{uuid4().hex}'
        service = RagService(self.jobs.embedding(operation_id), store, knowledge_base_dir="immutable-manifest",
            chunk_size=value.configuration["chunk_size"], chunk_overlap=value.configuration["chunk_overlap"],
            retrieval_mode=strategy, authorization_policy=lambda: self._allowed(actor, base.id, value.id),
            reference_policy=self.settings.rag_reference_policy,
            default_top_k=self.settings.rag_default_top_k,
            vector_candidates=self.settings.rag_vector_candidates,
            bm25_candidates=self.settings.rag_bm25_candidates,
            rrf_k=self.settings.rag_rrf_k,
            reranker=build_reranker(self.settings, operation_id=operation_id+':rerank'),
            reranker_candidate_k=self.settings.rag_reranker_candidate_k)
        service.loader = SimpleNamespace(load_directory=lambda _: [KnowledgeSection.model_validate(c.model_dump()) for c in chunks])
        service.versions = SimpleNamespace(load=lambda: (payload, chunks, store), validate_vector=self.jobs_checked_vector)
        if payload["configuration"] != service._configuration():
            raise ConflictError("索引与当前分词/模型配置不兼容")
        return service, value, chunks

    @staticmethod
    def jobs_checked_vector(chunks, store):
        from app.rag.versioned_index import VersionedIndex
        VersionedIndex.validate_vector(chunks, store)

    def search_for_actor(self, actor, query, top_k=None, document_type=None, *, base_id=None, strategy=None, index_id=None):
        started = time.perf_counter()
        selected = base_id or self.default_base_id
        if selected is None:
            choices = [b for b in self.management.list_bases(actor) if b.status == "ACTIVE" and b.active_index_id]
            if len(choices) != 1:
                raise BusinessError("请指定有权限的知识库；未设置唯一默认知识库", 409)
            selected = choices[0].id
        try:
            service, value, _ = self.prepare(actor, selected, strategy or self.default_strategy, index_id=index_id)
            results = service.search(query, top_k, document_type)
            allowed = self._allowed(actor, selected, value.id)
            results = [x for x in results if x.chunk_id in allowed]
            results = [x.model_copy(update={"final_rank": rank}) for rank, x in enumerate(results, 1)]
            final_positions = {x.chunk_id: x.final_rank for x in results}
            self.last_candidates = [x.model_copy(update={"final_rank": final_positions.get(x.chunk_id)})
                                    for x in service.last_candidates if x.chunk_id in allowed]
            self.last_search_stats = {**service.last_search_stats, "base_id": value.base_id, "index_id": value.id, "index_version": value.version,
                "scope": "OFFLINE_SYNTHETIC_NOT_SEMANTIC" if self.offline else 'REAL_EMBEDDING_NOT_BLIND', "duration_ms": (time.perf_counter() - started) * 1000}
            self.management.audit(actor, "RAG_SEARCHED", "KnowledgeBase", selected,
                {"result": "SUCCESS", "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
                 "duration_ms": self.last_search_stats["duration_ms"], "returned": len(results),
                 "index_id": value.id, "strategy": service.retrieval_mode, "scope": self.jobs.scope()})
            self.session.commit()
            return results
        except Exception as exc:
            self.session.rollback()
            self.management.audit(actor, "RAG_SEARCH_FAILED", "KnowledgeBase", selected,
                {"result": "FAILED", "error_type": type(exc).__name__[:80], "duration_ms": (time.perf_counter() - started) * 1000})
            self.session.commit()
            raise

    def revalidate_cached(self, actor, proof, hits):
        """Fresh SQL authorization only; never embed/search or load an index here."""
        def deny():
            raise BusinessError('知识证据已失效，请重新查询', 403, 'KNOWLEDGE_CACHE_INVALID')
        if not isinstance(proof, dict) or not isinstance(hits, list):
            deny()
        if any(type(proof.get(k)) is not int for k in ('base_id', 'index_id', 'user_id')) or proof['user_id'] != actor.id:
            deny()
        issued = proof.get('authorized_at')
        if isinstance(issued, bool) or not isinstance(issued, (int, float)) or not math.isfinite(issued) or not 0 <= time.time()-issued <= 30:
            deny()
        current = self.session.scalar(select(User).where(User.id == actor.id).execution_options(populate_existing=True))
        base = self.session.scalar(select(KnowledgeBase).where(KnowledgeBase.id == proof['base_id']).execution_options(populate_existing=True))
        index = self.session.scalar(select(KnowledgeIndexVersion).where(KnowledgeIndexVersion.id == proof['index_id']).execution_options(populate_existing=True))
        if (current is None or not current.is_active or base is None or index is None or base.status != 'ACTIVE' or
                not self.management.may_read(base, current) or base.active_index_id != index.id or
                index.base_id != base.id or index.status != 'PUBLISHED'):
            deny()
        ids = [h.get('chunk_id') if isinstance(h, dict) else None for h in hits]
        if any(not isinstance(k, str) or not k for k in ids) or len(ids) != len(set(ids)):
            deny()
        allowed = self._allowed(current, base.id, index.id)
        if not set(ids) <= allowed:
            deny()
        records = {r.chunk_id:r for r in self.session.scalars(select(KnowledgeChunkRecord).where(
            KnowledgeChunkRecord.index_id == index.id, KnowledgeChunkRecord.chunk_id.in_(ids)))}
        if set(records) != set(ids):
            deny()
        for hit in hits:
            if hit.get('index_version') != index.version or any(hit.get(k) != v for k,v in records[hit['chunk_id']].metadata_json.items()):
                deny()

    @staticmethod
    def aggregate_unique(cases, retrieved, k):
        if len({case.id for case in cases}) != len(cases) or any(len(ids) != len(set(ids)) for ids in retrieved.values()):
            raise BusinessError("评测拒绝重复问题ID或结果ID", 422)
        return aggregate(cases, retrieved, k)

    def evaluate(self, actor, index_id, dataset, strategy="vector"):
        self.management.admin(actor)
        value = self.management.index(actor, index_id, write=True)
        service, _, chunks = self.prepare(actor, value.base_id, strategy, index_id=value.id)
        if dataset not in {"development", "fixed"}:
            raise BusinessError("评测集必须来自固定白名单", 422)
        filename = "rag_hybrid_qrels.json" if dataset == "development" else "stage3_rag_holdout.json"
        path = Path(__file__).resolve().parents[2] / "tests/fixtures" / filename
        rows = load_json_dataset(path)
        labels = [(r, r["expected"] if dataset == "fixed" else ([[r["source"], r["section"]]] if r["source"] else [])) for r in rows]
        missing = [(r["id"], source, section) for r, expected in labels for source, section in expected
                   if not any(c.source == source and c.section == section for c in chunks)]
        records, retrieved = [], {}
        if missing:
            metrics, status = {"reason": "MISSING_LABEL_TARGETS", "missing": missing}, "BLOCKED"
        else:
            cases = resolve_expected_cases(rows, chunks) if dataset == "fixed" else resolve_source_section_cases(rows, chunks)
            for case in cases:
                started = time.perf_counter()
                try:
                    hits = service.search(case.query, 4, access_scope=case.access_scope)
                except Exception as exc:
                    records.append({"id": case.id, "query": case.query, "expected": sorted(case.relevant_ids),
                        "status": "ERROR", "error_type": type(exc).__name__,
                        "latency_ms": (time.perf_counter() - started) * 1000})
                    metrics, status = {"reason": "RETRIEVAL_ERROR", "failed_question": case.id,
                        "error_type": type(exc).__name__, "scope": self.jobs.scope(), "strategy": strategy}, "ERROR"
                    break
                retrieved[case.id] = [h.chunk_id for h in hits]
                records.append({"id": case.id, "query": case.query, "expected": sorted(case.relevant_ids),
                    "returned": [h.model_dump() for h in hits], "latency_ms": (time.perf_counter() - started) * 1000,
                    "metrics": self.aggregate_unique([case], {case.id: retrieved[case.id]}, 4).as_dict(),
                    "status": "COMPLETED", "should_refuse": not case.answerable})
            else:
                values = self.aggregate_unique(cases, retrieved, 4)
                metrics = {**values.as_dict(), "scope": "OFFLINE_HASH_EXPOSED_DATASET_NOT_BLIND" if self.offline else "REAL_EMBEDDING_EXPOSED_DATASET_NOT_BLIND", "strategy": strategy,
                           "generation_quality": "NOT RUN", "thresholds": {"recall": .95, "ndcg": .65}}
                metrics['acceptance_gates'] = acceptance_gates(values.as_dict(),
                    negative_questions=values.queries-values.answerable_queries,
                    false_positive_questions=values.unanswerable_with_results)
                status = "PASS" if values.recall_at_k is not None and values.recall_at_k >= .95 and values.ndcg >= .65 else "FAIL"
            # Additive observation report only: retain historical status,
            # thresholds, error records and publication behavior unchanged.
            metrics["pipeline"] = evaluate_observations(cases, [Observation(
                id=row["id"], status=row["status"],
                retrieved=tuple(hit["chunk_id"] for hit in row.get("returned", [])),
                error_type=row.get("error_type")) for row in records],
                k=4, dataset_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                corpus_version=fingerprint(value.snapshot), model_version=value.model_revision,
                strategy=strategy, scope="OFFLINE_HASH_EXPOSED_DATASET_NOT_BLIND" if self.offline else "REAL_EMBEDDING_EXPOSED_DATASET_NOT_BLIND")
            # The legacy metrics JSON is reproducible for identical inputs.
            # Actual timing remains in original per-question records, never
            # rounded/zeroed or deleted to make metric comparisons equal.
            metrics["pipeline"]["performance"]["latency_source"] = "evaluation.cases[].latency_ms"
        evaluation = KnowledgeEvaluationRun(index_id=value.id, actor_id=actor.id, dataset=dataset,
            dataset_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), status=status, metrics=metrics, cases=records)
        return self.jobs._finish_validation(actor, value, evaluation, "RAG_EVALUATION_COMPLETED",
            {"dataset": dataset, "strategy": strategy, "scope": self.jobs.scope()})
