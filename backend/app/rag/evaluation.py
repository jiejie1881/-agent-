"""Offline retrieval-quality evaluation primitives.

The module deliberately holds only deterministic, network-free pieces so that
the same code can serve three consumers without duplicating arithmetic:

* the historical CLI scripts under ``backend/tools`` (frozen evidence format),
* pytest-based regression tests,
* the RAG admin console's evaluation centre (Phase 3).

Metric semantics are frozen to match ``docs/evidence/v1-stage7/rag-quality.json``:

* ``Recall@K``  - macro average over *answerable* queries only.
* ``Precision@K`` - macro average over *all* queries with a fixed denominator K.
* ``MRR@K``     - average over *all* queries, first relevant hit only.
* ``nDCG@K``    - average over *all* queries, binary gains, unanswerable = 0.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from app.rag.bm25_index import tokenize
from app.rag.embedding_client import EmbeddingClient

HASH_EMBEDDING_DIMENSION = 192


class DeterministicHashEmbedding(EmbeddingClient):
    """Local stand-in embedding for pipeline tests; never a semantic model.

    Deterministic hashing keeps evaluation reproducible offline, but the
    resulting vectors carry no semantic similarity. Metrics produced with this
    embedding must never be reported as real retrieval quality.
    """

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        vector = [0.0] * HASH_EMBEDDING_DIMENSION
        for token in tokenize(text):
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % len(vector)
            vector[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


# --------------------------------------------------------------------------
# Metric primitives
# --------------------------------------------------------------------------


def dcg(gains: Iterable[float]) -> float:
    return sum(
        (2**gain - 1) / math.log2(position + 2)
        for position, gain in enumerate(gains)
    )


def precision_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Fixed denominator K so that empty results are penalised, not rewarded."""
    _require_positive_k(k)
    relevant_set = set(relevant)
    return sum(item in relevant_set for item in retrieved[:k]) / k


def recall_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    _require_positive_k(k)
    relevant_set = set(relevant)
    if not relevant_set:
        raise ValueError("recall is undefined without relevant chunks")
    return sum(item in relevant_set for item in retrieved[:k]) / len(relevant_set)


def reciprocal_rank(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    _require_positive_k(k)
    relevant_set = set(relevant)
    for rank, item in enumerate(retrieved[:k], 1):
        if item in relevant_set:
            return 1 / rank
    return 0.0


def ndcg_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    _require_positive_k(k)
    relevant_set = set(relevant)
    ideal = [1] * min(k, len(relevant_set))
    if not ideal:
        return 0.0
    gains = [1 if item in relevant_set else 0 for item in retrieved[:k]]
    return dcg(gains) / dcg(ideal)


def _require_positive_k(k: int) -> None:
    if k < 1:
        raise ValueError("k must be positive")


# --------------------------------------------------------------------------
# Cases and aggregation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalCase:
    """One labelled query. An empty ``relevant_ids`` marks an unanswerable case."""

    id: str
    query: str
    relevant_ids: frozenset[str] = field(default_factory=frozenset)
    access_scope: str = "public"

    @property
    def answerable(self) -> bool:
        return bool(self.relevant_ids)


@dataclass(frozen=True)
class RetrievalMetrics:
    k: int
    queries: int
    answerable_queries: int
    recall_at_k: float | None
    precision_at_k: float
    mrr: float
    ndcg: float
    hit_ratio: float
    empty_result_ratio: float
    unanswerable_with_results: int

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "k": self.k,
            "queries": self.queries,
            "answerable_queries": self.answerable_queries,
            "recall_at_k": self.recall_at_k,
            "precision_at_k": self.precision_at_k,
            "mrr": self.mrr,
            "ndcg": self.ndcg,
            "hit_ratio": self.hit_ratio,
            "empty_result_ratio": self.empty_result_ratio,
            "unanswerable_with_results": self.unanswerable_with_results,
        }


def aggregate(
    cases: Sequence[EvalCase],
    retrieved_by_id: dict[str, Sequence[str]],
    k: int,
) -> RetrievalMetrics:
    """Aggregate per-query metrics with the frozen macro-averaging rules."""
    _require_positive_k(k)
    if len(retrieved_by_id) != len(cases) or any(
        case.id not in retrieved_by_id for case in cases
    ):
        raise ValueError("every case needs exactly one retrieval result")
    if not cases:
        raise ValueError("evaluation needs at least one case")

    recalls: list[float] = []
    precisions: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    hits = empty = unanswerable_with_results = 0

    for case in cases:
        retrieved = list(retrieved_by_id[case.id])[:k]
        if retrieved:
            hits += 1
        else:
            empty += 1
        if not case.relevant_ids and retrieved:
            unanswerable_with_results += 1
        precisions.append(precision_at_k(retrieved, case.relevant_ids, k))
        reciprocal_ranks.append(reciprocal_rank(retrieved, case.relevant_ids, k))
        ndcgs.append(ndcg_at_k(retrieved, case.relevant_ids, k))
        if case.answerable:
            recalls.append(recall_at_k(retrieved, case.relevant_ids, k))

    total = len(cases)
    return RetrievalMetrics(
        k=k,
        queries=total,
        answerable_queries=len(recalls),
        recall_at_k=statistics.mean(recalls) if recalls else None,
        precision_at_k=statistics.mean(precisions),
        mrr=statistics.mean(reciprocal_ranks),
        ndcg=statistics.mean(ndcgs),
        hit_ratio=hits / total,
        empty_result_ratio=empty / total,
        unanswerable_with_results=unanswerable_with_results,
    )


def latency_summary(latencies: Sequence[float]) -> dict[str, float]:
    if not latencies:
        return {"mean_latency_ms": 0.0, "p50_latency_ms": 0.0, "p95_latency_ms": 0.0}
    ordered = sorted(latencies)
    return {
        "mean_latency_ms": statistics.mean(latencies),
        "p50_latency_ms": statistics.median(latencies),
        "p95_latency_ms": ordered[math.ceil(0.95 * len(ordered)) - 1],
    }


# --------------------------------------------------------------------------
# Dataset loading
# --------------------------------------------------------------------------


def load_json_dataset(path: str | Path) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"{path} must contain a non-empty JSON list")
    return payload


def resolve_source_section_cases(rows: Sequence[dict], chunks: Sequence) -> list[EvalCase]:
    """Resolve ``source`` + ``section`` labels (development set format).

    A row without ``source`` is treated as unanswerable. Every labelled row must
    resolve to at least one chunk, otherwise the label set drifted from corpus.
    """
    by_label: dict[tuple[str, str], set[str]] = {}
    for chunk in chunks:
        by_label.setdefault((chunk.source, chunk.section), set()).add(chunk.chunk_id)

    cases: list[EvalCase] = []
    for row in rows:
        source = row.get("source")
        if not source:
            cases.append(EvalCase(id=row["id"], query=row["query"]))
            continue
        label = (source, row["section"])
        ids = by_label.get(label)
        if not ids:
            raise ValueError(f"no chunk matches label {label} for {row['id']}")
        cases.append(EvalCase(id=row["id"], query=row["query"], relevant_ids=frozenset(ids)))
    return cases


def resolve_expected_cases(rows: Sequence[dict], chunks: Sequence) -> list[EvalCase]:
    """Resolve the holdout format where ``expected`` is a list of label pairs."""
    by_label: dict[tuple[str, str], set[str]] = {}
    for chunk in chunks:
        by_label.setdefault((chunk.source, chunk.section), set()).add(chunk.chunk_id)

    cases: list[EvalCase] = []
    for row in rows:
        ids: set[str] = set()
        for source, section in row.get("expected") or []:
            matched = by_label.get((source, section))
            if not matched:
                raise ValueError(f"no chunk matches label {(source, section)} for {row['id']}")
            ids |= matched
        cases.append(
            EvalCase(
                id=row["id"],
                query=row["query"],
                relevant_ids=frozenset(ids),
                access_scope=row.get("access_scope", "public"),
            )
        )
    return cases


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


def evaluate_service_modes(
    service,
    cases: Sequence[EvalCase],
    *,
    modes: Sequence[str] = ("bm25", "vector", "hybrid"),
    k: int = 4,
) -> dict[str, dict]:
    """Run every strategy over the same corpus and cases.

    ``service`` is a :class:`RagService`; the caller owns index construction and
    isolation. Nothing here reaches the network unless the injected embedding
    client does, which is why tests only ever inject the hash stand-in.
    """
    results: dict[str, dict] = {}
    for mode in modes:
        service.retrieval_mode = mode
        retrieved: dict[str, list[str]] = {}
        latencies: list[float] = []
        cases_out: list[dict] = []
        for case in cases:
            started = time.perf_counter()
            hits = service.search(case.query, k, access_scope=case.access_scope)
            latency = (time.perf_counter() - started) * 1000
            latencies.append(latency)
            ids = [item.chunk_id for item in hits]
            retrieved[case.id] = ids
            cases_out.append(
                {
                    "id": case.id,
                    "query": case.query,
                    "qrels": sorted(case.relevant_ids),
                    "returned": [item.model_dump() for item in hits],
                    "stats": dict(getattr(service, "last_search_stats", {})),
                    "relevant_returned": sum(item in case.relevant_ids for item in ids),
                    "latency_ms": latency,
                }
            )
        metrics = aggregate(cases, retrieved, k)
        results[mode] = {
            **metrics.as_dict(),
            **latency_summary(latencies),
            "cases": cases_out,
        }
    return results
