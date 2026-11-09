"""Network/file-free observation evaluation. Never generates or judges answers.

Retrieval arithmetic is delegated unchanged to evaluation.aggregate. Missing,
failed and timed-out observations stay in the dataset denominator. Optional
answer scores require explicit review provenance; absent measurements stay null.
This report cannot validate an index, authorize publishing, or open a real gate.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import mean
from typing import Sequence

from app.rag.evaluation import EvalCase, aggregate


@dataclass(frozen=True)
class Observation:
    id: str
    status: str = "COMPLETED"
    retrieved: tuple[str, ...] = ()
    duration_ms: float | None = None
    refused: bool | None = None
    # Relative to request start, one timestamp per output TOKEN, not SSE event.
    token_times_ms: tuple[float, ...] = ()
    generation_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost: float | None = None
    tool_attempts: int | None = None
    tool_successes: int | None = None
    retries: int | None = None
    error_type: str | None = None

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id or self.status not in {"COMPLETED", "ERROR", "TIMEOUT", "MISSING"}:
            raise ValueError("Invalid observation identity/status")
        if not isinstance(self.retrieved, tuple) or any(not isinstance(x, str) or not x for x in self.retrieved):
            raise ValueError("Retrieved identifiers must be an immutable tuple")
        if len(set(self.retrieved)) != len(self.retrieved):
            raise ValueError("Duplicate retrieved identifiers")
        if self.status != "COMPLETED" and (self.retrieved or self.refused is not None):
            raise ValueError("Unfinished observation cannot be successful retrieval/refusal")
        if self.refused is not None and type(self.refused) is not bool:
            raise ValueError("Refusal must be explicit or unknown")
        for value in (self.duration_ms, self.generation_ms, self.cost, *self.token_times_ms):
            if value is not None and (type(value) not in {int, float} or not math.isfinite(value) or value < 0):
                raise ValueError("Invalid measurement")
        for value in (self.input_tokens, self.output_tokens, self.tool_attempts, self.tool_successes, self.retries):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("Invalid count")
        if (self.tool_attempts is None) != (self.tool_successes is None):
            raise ValueError("Tool numerator and denominator must be supplied together")
        if self.tool_successes is not None and self.tool_successes > self.tool_attempts:
            raise ValueError("Tool successes exceed attempts")
        if not isinstance(self.token_times_ms, tuple) or tuple(sorted(self.token_times_ms)) != self.token_times_ms:
            raise ValueError("Token timestamps must be ordered")
        if self.token_times_ms and (self.output_tokens != len(self.token_times_ms) or self.duration_ms is None or
                                    self.token_times_ms[-1] > self.duration_ms):
            raise ValueError("Token timing/usage mismatch")


@dataclass(frozen=True)
class AnswerReview:
    """Externally supplied review, not automatic semantic verification."""
    id: str
    kind: str  # HUMAN / CALIBRATED_JUDGE / OFFLINE_FIXTURE
    evaluator_version: str
    basis: str
    faithfulness: float | None = None
    correctness: float | None = None
    relevance: float | None = None
    hallucinated: bool | None = None
    solved: bool | None = None

    def __post_init__(self):
        if self.kind not in {"HUMAN", "CALIBRATED_JUDGE", "OFFLINE_FIXTURE"} or not self.evaluator_version or not self.basis:
            raise ValueError("Review provenance is required")
        for value in (self.faithfulness, self.correctness, self.relevance):
            if value is not None and (type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError("Review score outside [0, 1]")
        for value in (self.hallucinated, self.solved):
            if value is not None and type(value) is not bool:
                raise ValueError("Review decisions must be explicit")


def _fraction(numerator, denominator):
    return numerator / denominator if denominator else None


def _measurement(values):
    values = list(values)
    return {"value": mean(values) if values else None, "measured": len(values),
            "status": "MEASURED" if values else "NOT RUN"}


def _percentile(values, quantile):
    """Linear interpolation, same definition for P50/P95/P99."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    low = math.floor(position)
    return ordered[low] + (ordered[math.ceil(position)] - ordered[low]) * (position - low)


def evaluate_observations(cases: Sequence[EvalCase], observations: Sequence[Observation], *, k: int,
                          dataset_sha256: str, corpus_version: str, model_version: str,
                          strategy: str, scope: str, reviews: Sequence[AnswerReview] = ()) -> dict:
    """Evaluate fixed inputs once. Caller owns authorization and evidence storage.

    An ERROR contributes an empty list to frozen retrieval metrics, but never
    counts as a correct refusal. Review means explicitly disclose their measured
    subset; they are not estimates over unreviewed answers. Cost per solved
    problem requires complete costs and complete solved labels.
    """
    if type(k) is not int or k < 1 or not cases:
        raise ValueError("Nonempty dataset and positive integer K required")
    case_ids = [c.id for c in cases]
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("Duplicate case IDs")
    for items in (observations, reviews):
        ids = [x.id for x in items]
        if len(ids) != len(set(ids)) or not set(ids) <= set(case_ids):
            raise ValueError("Duplicate or unknown observation/review ID")
    if not all(isinstance(v, str) and v.strip() for v in (dataset_sha256, corpus_version, model_version, strategy, scope)):
        raise ValueError("Version and scope provenance required")
    by_id = {o.id: o for o in observations}
    rows = [by_id.get(c.id, Observation(c.id, "MISSING")) for c in cases]
    completed = {o.id for o in rows if o.status == "COMPLETED"}
    if any(r.id not in completed for r in reviews):
        raise ValueError("Cannot review an incomplete answer")
    retrieval = aggregate(cases, {o.id: o.retrieved for o in rows}, k).as_dict()
    negatives = [c for c in cases if not c.answerable]
    false_candidates = sum(bool(by_id[c.id].retrieved) for c in negatives if c.id in completed)
    correct_refusals = sum(by_id[c.id].refused is True for c in negatives if c.id in completed)
    retrieved_negatives = sum(c.id in completed for c in negatives)
    refusal_negatives = sum(c.id in completed and by_id[c.id].refused is not None for c in negatives)
    positives = [c for c in cases if c.answerable]
    refusal_positives = sum(c.id in completed and by_id[c.id].refused is not None for c in positives)
    false_refusals = sum(by_id[c.id].refused is True for c in positives if c.id in completed)
    negative_nonrefusals = sum(by_id[c.id].refused is False for c in negatives if c.id in completed)
    all_behavior_measured = refusal_positives + refusal_negatives == len(cases)
    refusals = {"unanswerable_questions": len(negatives), "false_candidate_questions": false_candidates,
                "false_candidate_rate": _fraction(false_candidates, len(negatives)) if retrieved_negatives == len(negatives) else None,
                "negative_retrievals_measured": retrieved_negatives,
                "correct_refusals": correct_refusals,
                "correct_refusal_rate": _fraction(correct_refusals, len(negatives)) if refusal_negatives == len(negatives) else None,
                "negative_refusal_behaviors_measured": refusal_negatives,
                "correct_refusal_lower_bound": _fraction(correct_refusals, len(negatives)),
                "refusal_behavior_measured": sum(o.refused is not None for o in rows),
                "answerable_questions": len(positives),
                "answerable_refusal_behaviors_measured": refusal_positives,
                "answerable_false_refusal_questions": false_refusals,
                "answerable_false_refusal_rate": _fraction(false_refusals, len(positives)) if refusal_positives == len(positives) else None,
                "unanswerable_nonrefusal_questions": negative_nonrefusals,
                "unanswerable_nonrefusal_rate": _fraction(negative_nonrefusals, len(negatives)) if refusal_negatives == len(negatives) else None,
                "all_refused": (all(o.refused is True for o in rows)
                                if all_behavior_measured and positives and negatives else None),
                "behavior_note": "Requires explicit refusal observations; nonrefusal does not prove a correct or faithful answer",
                "note": "Candidates do not establish sufficient evidence; unknown/error is not correct refusal"}
    quality = {key: _measurement(getattr(r, field) for r in reviews if getattr(r, field) is not None)
               for key, field in {"faithfulness": "faithfulness", "answer_correctness": "correctness",
                                  "answer_relevance": "relevance", "hallucination_rate": "hallucinated"}.items()}
    quality["review_provenance"] = [{"id": r.id, "kind": r.kind, "evaluator_version": r.evaluator_version, "basis": r.basis} for r in reviews]
    quality["status"] = "REVIEWED_SUBSET" if reviews else "NOT RUN"
    latency = [o.duration_ms for o in rows if o.duration_ms is not None]
    performance = {"latency_ms": {"measured": len(latency), **{name: _percentile(latency, q)
                   for name, q in (("p50", .5), ("p95", .95), ("p99", .99))}},
                   "ttft_ms": _measurement(o.token_times_ms[0] for o in rows if o.token_times_ms),
                   "tpot_ms": _measurement((o.token_times_ms[-1] - o.token_times_ms[0]) / (len(o.token_times_ms)-1)
                                          for o in rows if len(o.token_times_ms) > 1),
                   "tps": _measurement(o.output_tokens / (o.generation_ms / 1000) for o in rows
                                       if o.output_tokens is not None and o.generation_ms is not None and o.generation_ms > 0)}
    def total(field):
        values = [getattr(o, field) for o in rows]
        return {"value": sum(values) if all(v is not None for v in values) else None,
                "measured": sum(v is not None for v in values), "required": len(rows)}
    costs = total("cost")
    solved = [r.solved for r in reviews if r.solved is not None]
    cost_per_solved = costs["value"] / sum(solved) if costs["value"] is not None and len(solved) == len(cases) and sum(solved) else None
    tool_rows = [o for o in rows if o.tool_attempts is not None]
    reliability = {"queries": len(rows), "completed": len(completed),
                   **{s.lower(): sum(o.status == s for o in rows) for s in ("ERROR", "TIMEOUT", "MISSING")},
                   "error_rate": sum(o.status != "COMPLETED" for o in rows) / len(rows),
                   "timeout_rate": sum(o.status == "TIMEOUT" for o in rows) / len(rows),
                   "tool_success_rate": _fraction(sum(o.tool_successes for o in tool_rows), sum(o.tool_attempts for o in tool_rows)),
                   "tool_rows_measured": len(tool_rows), "retries": total("retries")}
    return {"schema_version": "rag-observations-v1", "scope": scope, "status": "PARTIAL",
            "provenance": {"dataset_sha256": dataset_sha256, "corpus_version": corpus_version,
                           "model_version": model_version, "strategy": strategy, "k": k},
            "retrieval": retrieval, "refusal": refusals, "answer_quality": quality,
            "performance": performance, "usage": {"input_tokens": total("input_tokens"),
                "output_tokens": total("output_tokens"), "cost": costs, "cost_per_solved": cost_per_solved},
            "reliability": reliability, "cases": [{"id": c.id, "status": o.status,
                "expected": sorted(c.relevant_ids), "returned": list(o.retrieved), "error_type": o.error_type,
                "latency_ms": o.duration_ms, "refused": o.refused} for c, o in zip(cases, rows)],
            "limitations": ["No automatic semantic judge", "No real-model or publication acceptance implied",
                            "Unknown measurements remain null; review subset denominators are explicit"]}


def compare_reports(before: dict, after: dict) -> dict:
    """No cross-dataset/corpus/K comparisons disguised as strategy gains."""
    if any(r.get("schema_version") != "rag-observations-v1" or not r.get("scope") for r in (before, after)):
        return {"status": "BLOCKED", "mismatches": ["schema_or_scope"]}
    fields = ("dataset_sha256", "corpus_version", "k")
    mismatches = [f for f in fields if not before.get("provenance", {}).get(f) or
                  before["provenance"][f] != after.get("provenance", {}).get(f)]
    if before.get("scope") != after.get("scope"):
        mismatches.append("scope")
    if mismatches:
        return {"status": "BLOCKED", "mismatches": mismatches}
    old = {r["id"]: r for r in before["cases"]}
    if set(old) != {r["id"] for r in after["cases"]}:
        return {"status": "BLOCKED", "mismatches": ["case_ids"]}
    if any(old[r["id"]]["expected"] != r["expected"] for r in after["cases"]):
        return {"status": "BLOCKED", "mismatches": ["labels"]}
    return {"status": "COMPARABLE", "delta": {m: after["retrieval"][m] - before["retrieval"][m]
             if after["retrieval"][m] is not None and before["retrieval"][m] is not None else None
             for m in ("recall_at_k", "precision_at_k", "mrr", "ndcg")},
            "changed_cases": [{"id": r["id"], "before": old[r["id"]]["returned"], "after": r["returned"]}
                              for r in after["cases"] if old[r["id"]]["returned"] != r["returned"]]}
