"""Rank-only fusion; raw BM25 scores and cosine distances remain separate."""

from app.rag.exceptions import KnowledgeBaseNotReadyError
from app.rag.schemas import KnowledgeSearchResult


def _identity(chunk):
    return (
        chunk.content, chunk.source, chunk.document_id or chunk.source,
        chunk.document_name, chunk.document_type, chunk.section,
        chunk.chunk_index, chunk.access_scope,
    )


def reciprocal_rank_fusion(vectors, lexical, *, version: str, constant: int = 60):
    if constant < 1:
        raise ValueError("RRF constant must be positive")
    combined = {}
    identities = {}

    def validate(chunk):
        if not chunk.chunk_id or chunk.index_version not in {None, version}:
            raise KnowledgeBaseNotReadyError("知识库候选ID或版本不一致")
        identity = _identity(chunk)
        if chunk.chunk_id in identities and identities[chunk.chunk_id] != identity:
            raise KnowledgeBaseNotReadyError("知识库候选内容、文档或权限不一致")
        identities[chunk.chunk_id] = identity

    for rank, item in enumerate(vectors, 1):
        validate(item)
        if item.chunk_id in combined:
            continue
        combined[item.chunk_id] = item.model_copy(
            update={
                "vector_rank": rank,
                "index_version": version,
                "rrf_score": 1 / (constant + rank),
                "retrieval_sources": ["vector"],
            }
        )
    lexical_seen = set()
    for rank, (chunk, score) in enumerate(lexical, 1):
        validate(chunk)
        if chunk.chunk_id in lexical_seen:
            continue
        lexical_seen.add(chunk.chunk_id)
        item = combined.get(chunk.chunk_id)
        item = item or KnowledgeSearchResult(**chunk.model_dump(), score=None)
        combined[chunk.chunk_id] = item.model_copy(
            update={
                "bm25_rank": rank,
                "bm25_score": score,
                "index_version": version,
                "rrf_score": (item.rrf_score or 0) + 1 / (constant + rank),
                "retrieval_sources": item.retrieval_sources + ["bm25"],
            }
        )
    ranked = sorted(
        combined.values(), key=lambda item: (-(item.rrf_score or 0), item.chunk_id)
    )
    return [item.model_copy(update={"fusion_rank": rank}) for rank, item in enumerate(ranked, 1)]
