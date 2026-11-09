from __future__ import annotations

import logging
import time
from pathlib import Path

from app.rag.bm25_index import BUSINESS_WORDS, LEXICAL_POLICY, BM25Index
from app.rag.document_loader import KnowledgeDocumentLoader
from app.rag.exceptions import KnowledgeBaseError, KnowledgeBaseNotReadyError
from app.rag.fusion import reciprocal_rank_fusion
from app.rag.reranker import rerank_candidates
from app.rag.reference_policy import decide
from app.rag.schemas import (
    KnowledgeBaseStatus,
    KnowledgeBuildResult,
)
from app.rag.splitter import KnowledgeTextSplitter
from app.rag.versioned_index import VersionedIndex, digest

logger = logging.getLogger(__name__)
RETIRED_SOURCES = {"cold_chain_rules.md", "cargo_transport_rules.md"}


class RagService:
    def __init__(
        self,
        embedding_client,
        vector_store,
        *,
        knowledge_base_dir,
        chunk_size=800,
        chunk_overlap=120,
        default_top_k=4,
        loader=None,
        retrieval_mode="vector",
        vector_candidates=20,
        bm25_candidates=20,
        rrf_k=60,
        reranker=None,
        reranker_candidate_k=20,
        authorization_policy=None,
        reference_policy='legacy',
    ):
        if retrieval_mode not in {"vector", "bm25", "hybrid"}:
            raise ValueError("Invalid retrieval mode")
        self.embedding_client = embedding_client
        self.vector_store = vector_store
        self.knowledge_base_dir = knowledge_base_dir
        self.default_top_k = default_top_k
        self.loader = loader or KnowledgeDocumentLoader()
        self.splitter = KnowledgeTextSplitter(chunk_size, chunk_overlap)
        self.retrieval_mode = retrieval_mode
        self.vector_candidates = vector_candidates
        self.bm25_candidates = bm25_candidates
        self.rrf_k = rrf_k
        self.reranker = reranker
        self.reranker_candidate_k = reranker_candidate_k
        self.authorization_policy = authorization_policy
        self.reference_policy = reference_policy
        self.versions = VersionedIndex(vector_store)
        self.last_search_stats = {}
        self.last_candidates = []
        self._bm25_by_version = {}

    def _configuration(self):
        settings = getattr(self.embedding_client, "_settings", None)
        return {
            "chunk_size": self.splitter.chunk_size,
            "chunk_overlap": self.splitter.chunk_overlap,
            "tokenizer": "jieba-0.42.1",
            "lexical_policy": LEXICAL_POLICY,
            "dictionary": list(BUSINESS_WORDS),
            "embedding_client": type(self.embedding_client).__name__,
            "embedding_model": getattr(settings, "rag_embedding_model", None),
            "embedding_provider": getattr(settings, "rag_embedding_provider", None),
            "embedding_endpoint_sha256": (
                digest(getattr(settings, "rag_embedding_base_url", None))
                if getattr(settings, "rag_embedding_base_url", None)
                else None
            ),
        }

    def rebuild(self, *, activate=True, reuse_embeddings=False):
        snapshot = self._source_snapshot()
        chunks = self.splitter.split(
            self.loader.load_directory(self.knowledge_base_dir)
        )
        chunks = [
            c.model_copy(
                update={"chunk_id": digest(c.model_dump(exclude={"chunk_id"}))}
            )
            for c in chunks
        ]
        # Build and validate lexical index before any active pointer changes.
        BM25Index(chunks)
        if reuse_embeddings:
            old=self.versions.load()
            if old is None:
                raise KnowledgeBaseNotReadyError('没有可复用的已验证索引')
            payload,previous,store=old
            previous_config={k:v for k,v in payload['configuration'].items() if k!='lexical_policy'}
            current_config={k:v for k,v in self._configuration().items() if k!='lexical_policy'}
            if previous_config!=current_config or {c.chunk_id for c in chunks}!={c.chunk_id for c in previous}:
                raise KnowledgeBaseNotReadyError('仅分词升级可复用向量；模型或文档变化需重新构建')
            self.versions.validate_vector(previous,store)
            saved=store._existing_collection().get(include=['embeddings'])
            vectors=dict(zip(saved['ids'],saved['embeddings']))
            embeddings=[[float(v) for v in vectors[c.chunk_id]] for c in chunks]
        else:
            embeddings = self.embedding_client.embed_documents([c.content for c in chunks])

        def verify_source_snapshot():
            if snapshot != self._source_snapshot():
                raise KnowledgeBaseError("知识文档在索引构建期间发生变化，请重试")

        verify_source_snapshot()
        self.last_built_version = self.versions.publish(
            chunks,
            embeddings,
            self._configuration(),
            before_activate=verify_source_snapshot,
            activate=activate,
        )
        return KnowledgeBuildResult(
            documents=len({c.source for c in chunks}), chunks=len(chunks)
        )

    def _source_snapshot(self):
        from hashlib import sha256

        root = Path(self.knowledge_base_dir)
        try:
            return {
                path.name: sha256(path.read_bytes()).hexdigest()
                for path in root.iterdir()
                if path.is_file() and path.suffix.lower() in {".md", ".txt"}
            }
        except OSError:
            raise KnowledgeBaseError("无法读取知识文档快照") from None

    def _eligible(self, chunks, document_type, access_scope):
        authorized = self.authorization_policy() if self.authorization_policy is not None else None
        # These two historical filenames now contain retirement notices. Compare current
        # contents before candidate generation, including deletion and read failures.
        current = set()
        if any(c.source in RETIRED_SOURCES for c in chunks):
            sections = self.loader.load_directory(self.knowledge_base_dir)
            current = {
                (c.source, c.section, c.content) for c in self.splitter.split(sections)
            }
        return {
            c.chunk_id
            for c in chunks
            if c.access_scope == access_scope
            and (authorized is None or c.chunk_id in authorized)
            and (document_type is None or c.document_type == document_type)
            and (
                c.source not in RETIRED_SOURCES
                or (c.source, c.section, c.content) in current
            )
        }

    def search(self, query, top_k=None, document_type=None, *, access_scope="public"):
        started = time.perf_counter()
        self.last_candidates = []
        self.last_search_stats = {}
        query = query.strip()
        if not query:
            raise ValueError("知识库查询不能为空")
        limit = self.default_top_k if top_k is None else top_k
        if not 1 <= limit <= 10:
            raise ValueError("top_k 必须在 1 到 10 之间")
        active = self.versions.load()
        if active is None:
            if self.reranker is not None:
                raise KnowledgeBaseNotReadyError("精排需要已验证的版本化知识库")
            if self.retrieval_mode != "vector":
                raise KnowledgeBaseNotReadyError(
                    "混合知识库尚未初始化，请先构建候选版本"
                )
            # Legacy collections are public only. Never grant arbitrary scopes.
            if access_scope != "public":
                return []
            results = self.vector_store.search(
                self.embedding_client.embed_query(query),
                max(limit, self.vector_candidates),
                document_type,
            )
            eligible = self._eligible(results, document_type, access_scope)
            safe = [
                item.model_copy(update={"vector_rank": rank, "retrieval_sources": ["vector"]})
                for rank, item in enumerate(results, 1) if item.chunk_id in eligible
            ][:limit]
            decision = decide(query, safe, policy=self.reference_policy)
            if decision.refuse:
                self.last_search_stats = {'reference_policy': self.reference_policy, 'reference_reason': decision.reason, 'returned': 0}
                return []
            self.last_candidates = safe
            self.last_search_stats = {'reference_policy': self.reference_policy, 'reference_reason': decision.reason, 'returned': len(safe)}
            return [item.model_copy(update={"final_rank": rank}) for rank, item in enumerate(safe, 1)]
        payload, chunks, store = active
        if payload["configuration"] != self._configuration():
            raise KnowledgeBaseNotReadyError(
                "知识库分块、分词或向量模型配置已变化，请构建新版本"
            )
        allowed = self._eligible(chunks, document_type, access_scope)
        # Detect cross-store tampering even in single-route modes before filtering.
        try:
            self.versions.validate_vector(chunks, store)
        except KnowledgeBaseError:
            logger.warning("rag_integrity_failure version=%s", payload["version"])
            raise
        except Exception as exc:  # noqa: BLE001 - no unverified route may be used.
            logger.warning(
                "rag_integrity_unavailable version=%s type=%s",
                payload["version"],
                type(exc).__name__,
            )
            raise KnowledgeBaseNotReadyError(
                "知识库完整性校验暂不可用，检索已停止"
            ) from None
        vectors, lexical, degraded = [], [], []
        if self.retrieval_mode in {"vector", "hybrid"}:
            try:
                vectors = store.search(
                    self.embedding_client.embed_query(query),
                    self.vector_candidates,
                    document_type,
                    allowed,
                )
            except KnowledgeBaseNotReadyError:
                raise  # Metadata/version mismatch is never a degradation opportunity.
            except Exception:  # noqa: BLE001 - backend failures map to a safe route-level error.
                if self.retrieval_mode == "vector":
                    raise KnowledgeBaseError("向量检索暂不可用") from None
                degraded.append("vector")
        if self.retrieval_mode in {"bm25", "hybrid"}:
            try:
                index = self._bm25_by_version.get(payload["version"])
                if index is None:
                    index = BM25Index(chunks, reference_policy=self.reference_policy)
                    self._bm25_by_version[payload["version"]] = index
                lexical = index.search(query, allowed, self.bm25_candidates)
            except Exception:  # noqa: BLE001 - only degrade to the verified other route.
                if self.retrieval_mode == "bm25" or not vectors:
                    raise KnowledgeBaseError("关键词检索暂不可用") from None
                degraded.append("bm25")
        if len(degraded) == 2:
            raise KnowledgeBaseError("知识库检索暂不可用")
        vector_ids = {item.chunk_id for item in vectors}
        bm25_ids = {chunk.chunk_id for chunk, _ in lexical}
        unique_candidate_ids = vector_ids | bm25_ids
        fused = reciprocal_rank_fusion(
            vectors, lexical, version=payload["version"], constant=self.rrf_k
        )
        eligible = self._eligible(chunks, document_type, access_scope)
        safe_candidates = [item for item in fused if item.chunk_id in eligible]
        self.last_candidates = list(safe_candidates)
        reranker_status = "DISABLED"
        reranker_ms = 0.0
        if self.reranker is not None and safe_candidates:
            rerank_started = time.perf_counter()
            try:
                pool = safe_candidates[: max(limit, self.reranker_candidate_k)]
                ranked = rerank_candidates(query, pool, self.reranker)
                eligible = self._eligible(chunks, document_type, access_scope)
                safe_candidates = [item for item in ranked if item.chunk_id in eligible]
                reranker_status = "PASS"
            except Exception as exc:  # noqa: BLE001 - preserve validated RRF candidates on failure.
                reranker_status = "FALLBACK"
                logger.warning(
                    "rag_reranker_failure version=%s type=%s",
                    payload["version"],
                    type(exc).__name__,
                )
                eligible = self._eligible(chunks, document_type, access_scope)
                safe_candidates = [
                    item for item in safe_candidates if item.chunk_id in eligible
                ]
            reranker_ms = (time.perf_counter() - rerank_started) * 1000
            logger.info(
                "rag_reranker version=%s status=%s latency_ms=%.3f",
                payload["version"],
                reranker_status,
                reranker_ms,
            )
        results = [
            item.model_copy(update={"final_rank": rank})
            for rank, item in enumerate(safe_candidates[:limit], 1)
        ]
        decision = decide(query, results, policy=self.reference_policy)
        if decision.refuse:
            results = []
        self.last_search_stats = {
            "reference_policy": self.reference_policy,
            "reference_reason": decision.reason,
            "vector_candidates": len(vectors),
            "bm25_candidates": len(lexical),
            "unique_candidates": len(unique_candidate_ids),
            "deduplicated_candidates": len(vector_ids)
            + len(bm25_ids)
            - len(unique_candidate_ids),
            "returned": len(results),
            "degraded": tuple(degraded),
            "reranker_status": reranker_status,
            "reranker_latency_ms": reranker_ms,
        }
        logger.info(
            "rag_search mode=%s version=%s vector_count=%d bm25_count=%d "
            "unique_count=%d result_count=%d degraded=%s latency_ms=%.3f",
            self.retrieval_mode,
            payload["version"],
            len(vectors),
            len(lexical),
            len(unique_candidate_ids),
            len(results),
            ",".join(degraded),
            (time.perf_counter() - started) * 1000,
        )
        return results

    def status(self):
        try:
            active = self.versions.load()
            if active:
                _, chunks, store = active
                self.versions.validate_vector(chunks, store)
                documents, count = len({c.source for c in chunks}), len(chunks)
            else:
                documents, count = self.vector_store.status()
            return KnowledgeBaseStatus(
                ready=count > 0, documents=documents, chunks=count
            )
        except KnowledgeBaseError:
            return KnowledgeBaseStatus(ready=False, documents=0, chunks=0)
