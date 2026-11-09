"""Protocol/fault tests only: fabricated scores never measure model quality."""
from types import SimpleNamespace

import pytest

from app.rag.reranker import rerank_candidates
from app.rag.schemas import KnowledgeSearchResult
from tests.test_rag_hybrid_safety import chunk


def candidates():
    return [KnowledgeSearchResult(**chunk(key).model_dump(), rrf_score=.01,
                                  fusion_rank=rank, vector_rank=rank, final_rank=rank)
            for rank, key in enumerate(("b", "a"), 1)]


@pytest.mark.parametrize("raw", [
    {"1": 50, "2": -50}, "12", [True, False], ["1", "2"],
    [[1], [2]], None, 1, [1], [float("nan"), 1], [float("inf"), 1],
])
def test_non_numeric_or_malformed_scores_are_rejected(raw):
    with pytest.raises(ValueError):
        rerank_candidates("anonymous", candidates(), SimpleNamespace(score=lambda *args: raw))


def test_empty_pool_does_not_invoke_adapter():
    def forbidden(*args):
        pytest.fail("Empty candidate pool must never invoke a model")
    assert rerank_candidates("anonymous", [], SimpleNamespace(score=forbidden)) == []


@pytest.mark.parametrize("invalid_id", ["", "b"])
def test_ambiguous_candidate_ids_are_rejected_before_model(invalid_id):
    rows = candidates()
    rows[1] = rows[1].model_copy(update={"chunk_id": invalid_id})
    invoked = []
    with pytest.raises(ValueError):
        rerank_candidates("anonymous", rows, SimpleNamespace(score=lambda *args: invoked.append(True) or [1, 2]))
    assert not invoked


def test_only_permutation_and_score_rank_fields_change():
    rows = candidates()
    original = [x.model_dump() for x in rows]
    ranked = rerank_candidates("anonymous", rows, SimpleNamespace(score=lambda *args: [-2.5, 8]))
    assert [x.chunk_id for x in ranked] == ["a", "b"]
    assert {x.chunk_id for x in ranked} == {x.chunk_id for x in rows}
    assert [x.model_dump() for x in rows] == original
    by_id = {x["chunk_id"]: x for x in original}
    for rank, row in enumerate(ranked, 1):
        assert row.reranker_rank == rank
        actual = row.model_dump()
        for key, value in by_id[row.chunk_id].items():
            if key not in {"reranker_rank", "reranker_score"}:
                assert actual[key] == value


def test_mutating_documents_argument_cannot_change_candidate_metadata():
    rows = candidates()
    original = [x.model_dump() for x in rows]
    def mutate(query, documents):
        documents[:] = ["malicious", "replacement"]
        return [1., 2.]
    ranked = rerank_candidates("anonymous", rows, SimpleNamespace(score=mutate))
    assert [x.model_dump() for x in rows] == original
    assert {x.content for x in ranked} == {x.content for x in rows}
