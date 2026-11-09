"""Pure observations; synthetic scores/timings are metric fixtures, not model results."""
from copy import deepcopy

import pytest

from app.rag.evaluation import EvalCase, aggregate
from app.rag.evaluation_pipeline import AnswerReview, Observation, compare_reports, evaluate_observations

CASES = [EvalCase("a", "synthetic load rule", frozenset({"right"})),
         EvalCase("b", "synthetic unknown", frozenset())]


def report(observations, *, cases=CASES, reviews=(), **kwargs):
    config = dict(k=4, dataset_sha256="synthetic-dataset", corpus_version="synthetic-corpus",
                  model_version="synthetic-model", strategy="hybrid", scope="OFFLINE_FIXTURE")
    return evaluate_observations(cases, observations, reviews=reviews, **(config | kwargs))


def test_frozen_retrieval_arithmetic_is_shared_and_not_redefined():
    observations = [Observation("a", retrieved=("wrong", "right")), Observation("b", retrieved=("wrong",))]
    result = report(observations)
    assert result["retrieval"] == aggregate(CASES, {"a": ["wrong", "right"], "b": ["wrong"]}, 4).as_dict()
    assert result["refusal"]["false_candidate_rate"] == 1
    assert result["refusal"]["correct_refusal_rate"] is None
    assert result["refusal"]["correct_refusal_lower_bound"] == 0
    assert result["status"] == "PARTIAL"


def test_missing_timeout_error_remain_in_denominator_and_never_count_as_refusal():
    cases = CASES + [EvalCase("c", "more", frozenset()), EvalCase("d", "more", frozenset())]
    r = report([Observation("a", "TIMEOUT"), Observation("b", "ERROR", error_type="SyntheticError")], cases=cases)
    assert r["retrieval"]["queries"] == 4 and r["retrieval"]["recall_at_k"] == 0
    assert {k: r["reliability"][k] for k in ["error", "timeout", "missing", "error_rate"]} == dict(error=1, timeout=1, missing=2, error_rate=1)
    assert r["refusal"]["correct_refusals"] == 0
    assert r["refusal"]["false_candidate_rate"] is None
    assert r["refusal"]["correct_refusal_rate"] is None
    assert r["cases"][1]["error_type"] == "SyntheticError"


def test_empty_candidates_do_not_automatically_mean_correct_refusal():
    assert report([Observation("a"), Observation("b")])["refusal"]["correct_refusal_rate"] is None
    assert report([Observation("a"), Observation("b", refused=True)])["refusal"]["correct_refusal_rate"] == 1


def test_missing_measurements_are_null_not_free_or_successful():
    r = report([Observation("a"), Observation("b")])
    assert r["answer_quality"]["faithfulness"] == dict(value=None, measured=0, status="NOT RUN")
    assert r["performance"]["ttft_ms"]["value"] is None
    assert r["usage"]["cost"]["value"] is None and r["usage"]["cost_per_solved"] is None
    assert r["reliability"]["tool_success_rate"] is None


def test_review_subset_denominator_and_provenance_and_stream_arithmetic():
    trace = Observation("a", duration_ms=400, token_times_ms=(100, 200, 300), output_tokens=3,
                        generation_ms=250, input_tokens=9, cost=.2, tool_attempts=2, tool_successes=1, retries=1)
    review = AnswerReview("a", "OFFLINE_FIXTURE", "fixture-v1", "synthetic claim fixture", .5, 1, 1, False, True)
    r = report([trace, Observation("b", duration_ms=600, cost=.1)], reviews=[review])
    assert r["performance"]["ttft_ms"]["value"] == 100
    assert r["performance"]["tpot_ms"]["value"] == 100
    assert r["performance"]["tps"]["value"] == 12
    assert r["performance"]["latency_ms"]["p50"] == 500
    assert r["performance"]["latency_ms"]["p95"] == 590
    assert r["answer_quality"]["faithfulness"]["measured"] == 1
    assert r["answer_quality"]["review_provenance"][0]["kind"] == "OFFLINE_FIXTURE"
    assert r["reliability"]["tool_success_rate"] == .5
    assert r["usage"]["cost_per_solved"] is None  # missing solved label stays unknown


def test_cost_per_solved_requires_all_costs_and_all_labels():
    reviews = [AnswerReview("a", "OFFLINE_FIXTURE", "v1", "fixture", solved=True),
               AnswerReview("b", "OFFLINE_FIXTURE", "v1", "fixture", solved=False)]
    r = report([Observation("a", cost=2), Observation("b", cost=1)], reviews=reviews)
    assert r["usage"]["cost_per_solved"] == 3
    assert report([Observation("a", cost=2), Observation("b")], reviews=reviews)["usage"]["cost_per_solved"] is None


@pytest.mark.parametrize("kwargs", [
    {"retrieved": ("x", "x")}, {"retrieved": ["x"]}, {"duration_ms": float("nan")},
    {"cost": -1}, {"duration_ms": True}, {"input_tokens": 1.1}, {"output_tokens": True},
    {"tool_attempts": 0, "tool_successes": 1}, {"tool_successes": 0},
    {"token_times_ms": (2, 1), "output_tokens": 2, "duration_ms": 3},
    {"token_times_ms": (1,), "output_tokens": 2, "duration_ms": 3},
    {"token_times_ms": (9,), "output_tokens": 1, "duration_ms": 3},
    {"status": "TIMEOUT", "retrieved": ("x",)}, {"status": "ERROR", "refused": True}, {"refused": 1},
])
def test_invalid_observations_are_rejected(kwargs):
    with pytest.raises(ValueError):
        Observation("a", **kwargs)


@pytest.mark.parametrize("observations", [[Observation("a"), Observation("a")], [Observation("unknown")]])
def test_duplicate_or_unknown_ids_fail_closed(observations):
    with pytest.raises(ValueError):
        report(observations)


def test_reviews_require_complete_answer_and_valid_provenance():
    with pytest.raises(ValueError):
        report([], reviews=[AnswerReview("a", "HUMAN", "v1", "basis")])
    with pytest.raises(ValueError):
        AnswerReview("a", "UNVERIFIED_JUDGE", "v1", "basis")
    with pytest.raises(ValueError):
        AnswerReview("a", "HUMAN", "v1", "basis", correctness=2)


def test_no_negative_denominator_is_na_and_empty_dataset_is_rejected():
    assert report([Observation("a")], cases=CASES[:1])["refusal"]["correct_refusal_rate"] is None
    with pytest.raises(ValueError):
        report([], cases=[])
    with pytest.raises(ValueError):
        report([], cases=CASES * 2)


@pytest.mark.parametrize("field", ["dataset_sha256", "corpus_version", "k", "scope"])
def test_comparison_rejects_incompatible_protocols(field):
    a = report([Observation("a"), Observation("b")])
    b = deepcopy(a)
    (b if field == "scope" else b["provenance"])[field] = "different"
    assert compare_reports(a, b)["status"] == "BLOCKED"


def test_comparison_keeps_sample_rank_changes_and_does_not_mutate_inputs():
    a = report([Observation("a", retrieved=("wrong",)), Observation("b")])
    b = report([Observation("a", retrieved=("right",)), Observation("b")], strategy="bm25")
    frozen = deepcopy(a)
    result = compare_reports(a, b)
    assert result["status"] == "COMPARABLE" and result["delta"]["recall_at_k"] == 1
    assert result["changed_cases"] == [{"id": "a", "before": ["wrong"], "after": ["right"]}]
    assert a == frozen
    changed = deepcopy(b); changed["cases"][0]["expected"] = []
    assert compare_reports(a, changed)["status"] == "BLOCKED"


def test_all_refusal_is_not_overall_acceptance():
    r = report([Observation("a", refused=True), Observation("b", refused=True)])
    assert r["retrieval"]["recall_at_k"] == 0
    assert r["status"] == "PARTIAL" and r["refusal"]["correct_refusal_rate"] == 1


def test_unknown_report_scope_or_schema_cannot_be_compared():
    a = report([Observation("a"), Observation("b")])
    for field in ("scope", "schema_version"):
        b = deepcopy(a); b.pop(field)
        assert compare_reports(a, b)["status"] == "BLOCKED"
