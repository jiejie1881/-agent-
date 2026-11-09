"""Metric contract tests for :mod:`app.rag.evaluation`.

The archived Stage 7 evidence is the reference implementation: if these tests
pass, the reusable module reproduces every published number bit-for-bit instead
of re-deriving a "close enough" metric.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.rag.evaluation import (
    HASH_EMBEDDING_DIMENSION,
    DeterministicHashEmbedding,
    EvalCase,
    aggregate,
    dcg,
    latency_summary,
    load_json_dataset,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    resolve_expected_cases,
    resolve_source_section_cases,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = PROJECT_ROOT / "docs/evidence/v1-stage7/rag-quality.json"
TOLERANCE = 1e-12


class FakeChunk:
    def __init__(self, chunk_id: str, source: str, section: str) -> None:
        self.chunk_id = chunk_id
        self.source = source
        self.section = section


def test_dcg_matches_hand_computed_value():
    # 1/log2(2) + 1/log2(3) + 1/log2(4) = 1 + 0.6309297536 + 0.5
    assert dcg([1, 1, 1]) == pytest.approx(2.1309297536, rel=0, abs=1e-9)
    assert dcg([]) == 0


def test_precision_uses_fixed_denominator():
    assert precision_at_k(["a", "b"], {"a"}, 4) == pytest.approx(0.25)
    # Empty results must be penalised, not skipped.
    assert precision_at_k([], {"a"}, 4) == 0.0
    # Results beyond K are ignored but the denominator stays K.
    assert precision_at_k(["a", "b", "c", "d", "e"], {"e"}, 4) == 0.0


def test_recall_requires_at_least_one_relevant_chunk():
    assert recall_at_k(["a", "b"], {"a", "b"}, 4) == 1.0
    assert recall_at_k(["a"], {"a", "b"}, 4) == 0.5
    with pytest.raises(ValueError):
        recall_at_k(["a"], set(), 4)


def test_reciprocal_rank_uses_first_hit_only():
    assert reciprocal_rank(["x", "a", "b"], {"a", "b"}, 4) == pytest.approx(0.5)
    assert reciprocal_rank(["a", "b"], {"a", "b"}, 4) == 1.0
    assert reciprocal_rank(["x", "y"], {"a"}, 4) == 0.0
    # A hit outside K does not score.
    assert reciprocal_rank(["x", "y", "z", "w", "a"], {"a"}, 4) == 0.0


def test_ndcg_ideal_is_truncated_to_k():
    # Two relevant chunks, K=4 -> ideal = [1, 1]; perfect ranking scores 1.0.
    assert ndcg_at_k(["a", "b"], {"a", "b"}, 4) == pytest.approx(1.0)
    # Four relevant chunks, K=2 -> ideal only has two gains.
    assert ndcg_at_k(["a", "b"], {"a", "b", "c", "d"}, 2) == pytest.approx(1.0)


def test_ndcg_is_zero_for_unanswerable_case():
    assert ndcg_at_k(["a", "b"], set(), 4) == 0.0
    assert ndcg_at_k([], set(), 4) == 0.0


def test_duplicate_ids_count_once_per_position():
    """Pinning current semantics: duplicates inflate scores, so callers dedupe."""
    assert precision_at_k(["a", "a"], {"a"}, 4) == pytest.approx(0.5)
    # Both positions match, so recall reaches 1.0 even though "b" was never seen.
    assert recall_at_k(["a", "a"], {"a", "b"}, 4) == pytest.approx(1.0)


def test_aggregate_mixes_answerable_and_unanswerable_cases():
    cases = [
        EvalCase("q1", "one", frozenset({"a"})),
        EvalCase("q2", "two", frozenset({"b", "c"})),
        EvalCase("q3", "three", frozenset()),
    ]
    metrics = aggregate(cases, {"q1": ["a", "x"], "q2": ["x", "b"], "q3": ["y"]}, 4)
    assert metrics.queries == 3
    assert metrics.answerable_queries == 2
    # Recall ignores q3 entirely: (1.0 + 0.5) / 2
    assert metrics.recall_at_k == pytest.approx(0.75)
    # Precision keeps q3 in the denominator with fixed K=4: (1/4 + 1/4 + 0/4) / 3
    assert metrics.precision_at_k == pytest.approx(1 / 6)
    assert metrics.mrr == pytest.approx((1.0 + 0.5 + 0.0) / 3)
    assert metrics.hit_ratio == pytest.approx(1.0)
    assert metrics.empty_result_ratio == 0.0
    assert metrics.unanswerable_with_results == 1


def test_aggregate_rejects_missing_or_extra_results():
    cases = [EvalCase("q1", "one", frozenset({"a"}))]
    with pytest.raises(ValueError):
        aggregate(cases, {}, 4)
    with pytest.raises(ValueError):
        aggregate(cases, {"q1": ["a"], "q2": ["b"]}, 4)


def test_aggregate_requires_positive_k():
    with pytest.raises(ValueError):
        aggregate([EvalCase("q1", "one")], {"q1": []}, 0)


def test_latency_summary_handles_empty_and_small_samples():
    assert latency_summary([])["p50_latency_ms"] == 0.0
    summary = latency_summary([10.0, 20.0, 30.0])
    assert summary["p50_latency_ms"] == 20.0
    assert summary["p95_latency_ms"] == 30.0


def test_hash_embedding_is_deterministic_and_normalised():
    embedding = DeterministicHashEmbedding()
    first = embedding.embed_query("派车方案发布前检查车辆出勤")
    second = embedding.embed_query("派车方案发布前检查车辆出勤")
    assert first == second
    assert len(first) == HASH_EMBEDDING_DIMENSION
    assert math.isclose(math.sqrt(sum(v * v for v in first)), 1.0, abs_tol=1e-9)
    # Different text must not collapse to the same vector.
    assert embedding.embed_query("签收回单补传") != first


def test_load_json_dataset_rejects_empty(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_json_dataset(path)


def test_resolve_source_section_cases_maps_labels_to_chunk_ids():
    chunks = [FakeChunk("c1", "a.md", "S1"), FakeChunk("c2", "a.md", "S1")]
    rows = [
        {"id": "q1", "query": "x", "source": "a.md", "section": "S1"},
        {"id": "q2", "query": "y", "source": None, "section": ""},
    ]
    cases = resolve_source_section_cases(rows, chunks)
    assert cases[0].relevant_ids == frozenset({"c1", "c2"})
    assert cases[1].answerable is False


def test_resolve_source_section_cases_fails_on_drifted_label():
    with pytest.raises(ValueError):
        resolve_source_section_cases(
            [{"id": "q1", "query": "x", "source": "missing.md", "section": "S"}],
            [FakeChunk("c1", "a.md", "S1")],
        )


def test_resolve_expected_cases_supports_multi_evidence_and_unanswerable():
    chunks = [FakeChunk("c1", "a.md", "S1"), FakeChunk("c2", "b.md", "S2")]
    cases = resolve_expected_cases(
        [
            {"id": "h1", "query": "x", "expected": [["a.md", "S1"], ["b.md", "S2"]]},
            {"id": "h2", "query": "y", "expected": []},
        ],
        chunks,
    )
    assert cases[0].relevant_ids == frozenset({"c1", "c2"})
    assert cases[1].answerable is False


@pytest.mark.skipif(not EVIDENCE.exists(), reason="archived Stage 7 evidence missing")
@pytest.mark.parametrize("mode", ["bm25", "vector", "hybrid"])
def test_aggregate_reproduces_archived_stage7_evidence(mode):
    payload = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    recorded = payload["modes"][mode]
    cases = [
        EvalCase(case["id"], case["query"], frozenset(case["expected"]))
        for case in recorded["cases"]
    ]
    retrieved = {
        case["id"]: [item["chunk_id"] for item in case["returned"]]
        for case in recorded["cases"]
    }

    metrics = aggregate(cases, retrieved, k=4)

    assert metrics.answerable_queries == sum(c.answerable for c in cases)
    assert metrics.recall_at_k == pytest.approx(recorded["recall"], abs=TOLERANCE)
    assert metrics.precision_at_k == pytest.approx(recorded["precision"], abs=TOLERANCE)
    assert metrics.mrr == pytest.approx(recorded["mrr"], abs=TOLERANCE)
    assert metrics.ndcg == pytest.approx(recorded["ndcg"], abs=TOLERANCE)

    # Per-case arithmetic must match as well, not just the aggregate.
    for case, row in zip(cases, recorded["cases"]):
        ids = retrieved[case.id]
        assert precision_at_k(ids, case.relevant_ids, 4) == pytest.approx(
            row["precision"], abs=TOLERANCE
        )
        assert reciprocal_rank(ids, case.relevant_ids, 4) == pytest.approx(
            row["mrr"], abs=TOLERANCE
        )
        assert ndcg_at_k(ids, case.relevant_ids, 4) == pytest.approx(
            row["ndcg"], abs=TOLERANCE
        )
        if case.answerable:
            assert recall_at_k(ids, case.relevant_ids, 4) == pytest.approx(
                row["recall"], abs=TOLERANCE
            )
        else:
            assert row["recall"] is None
