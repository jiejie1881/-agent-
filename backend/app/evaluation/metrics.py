"""Deterministic observation evaluators; no providers, SDK clients or storage.

Missing observations remain in denominators. No evaluator performs semantic
inference: claim metrics require externally authored atomic claims/evidence.
These metrics are report-only and cannot authorize a deployment/publication.
"""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import math
from statistics import mean

from app.rag.evaluation import EvalCase, aggregate


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def ratio(a, b):
    return a / b if b else None


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def distribution(values):
    values = list(values)
    if any(not finite(v) for v in values):
        raise ValueError('Invalid nonnegative measurement')
    ordered = sorted(values)
    def percentile(q):
        if not ordered:
            return None
        p = (len(ordered) - 1) * q
        return ordered[math.floor(p)] + (ordered[math.ceil(p)] - ordered[math.floor(p)]) * (p % 1)
    return dict(n=len(values), mean=mean(values) if values else None,
                p50=percentile(.5), p95=percentile(.95),
                sufficiency='DESCRIPTIVE_ONLY' if values else 'NOT RUN')


def keyed(rows, allowed):
    result = {}
    for row in rows:
        key = row['id']
        if key in result or key not in allowed:
            raise ValueError('Duplicate or unknown observation ID')
        result[key] = row
    return result


def retrieval(cases, observations, ks=(1, 3, 5)):
    ids = [c.id for c in cases]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError('Nonempty unique dataset required')
    by_id = keyed(observations, set(ids))
    rankings = {}
    errors = 0
    false_candidates = refusals = measured_refusals = false_refusals = 0
    unanswered = sum(not c.answerable for c in cases)
    correct_abstention = 0
    for c in cases:
        row = by_id.get(c.id, {'status': 'MISSING'})
        status = row.get('status')
        if status not in {'COMPLETED', 'MISSING', 'ERROR', 'TIMEOUT'}:
            raise ValueError('Unknown execution status')
        ranked = row.get('retrieved', [])
        if not isinstance(ranked, list) or any(not isinstance(x, str) or not x for x in ranked) or len(ranked) != len(set(ranked)):
            raise ValueError('Rankings must contain unique nonempty IDs')
        if status != 'COMPLETED':
            if ranked or row.get('refused') is not None:
                raise ValueError('Failed execution cannot carry successful results')
            errors += 1
        else:
            refusal = row.get('refused')
            if refusal is not None:
                if type(refusal) is not bool:
                    raise ValueError('Explicit boolean refusal required')
                measured_refusals += 1
                correct_abstention += refusal == (not c.answerable)
                refusals += refusal and not c.answerable
                false_refusals += refusal and c.answerable
            false_candidates += not c.answerable and bool(ranked)
        rankings[c.id] = ranked if status == 'COMPLETED' else []
    metrics = {str(k): aggregate(cases, rankings, k).as_dict() for k in ks}
    # Existing hit_ratio means nonempty results, not a relevant hit. Keep it,
    # expose the separately named answerable relevant-hit metric.
    for k in ks:
        metrics[str(k)]['relevant_hit_rate_answerable'] = ratio(
            sum(bool(set(rankings[c.id][:k]) & c.relevant_ids) for c in cases if c.answerable),
            len(cases) - unanswered)
    return dict(at_k=metrics, total=len(cases), errors_or_missing=errors,
                no_answer=dict(total=unanswered, false_candidate_count=false_candidates,
                               false_candidate_rate=ratio(false_candidates, unanswered),
                               correct_refusal_lower_bound=ratio(refusals, unanswered),
                               false_refusals=false_refusals,
                               abstention_accuracy=ratio(correct_abstention, measured_refusals)
                               if measured_refusals == len(cases) else None,
                               measured_refusals=measured_refusals),
                note='Candidate presence is not sufficient evidence or an answer; missing refusal remains unknown')


def answer_quality(reference, prediction):
    """Exact atomic proposition evaluation, NOT a semantic or LLM judge.

    reference: claims, evidence {chunk_id: supported_claims}, provenance.
    prediction: claims [{text, citations}], refused. Facts and labels must
    be authored outside the prediction adapter. Free text needs human review.
    """
    if not reference.get('provenance'):
        raise ValueError('Reference provenance required')
    expected = set(reference['claims'])
    evidence = {k: set(v) for k, v in reference['evidence'].items()}
    predicted = prediction.get('claims')
    if predicted is None:
        return dict(status='NOT RUN', reason='No externally segmented atomic claims')
    texts = [x['text'] for x in predicted]
    if len(set(texts)) != len(texts) or any(not isinstance(t, str) or not t for t in texts):
        raise ValueError('Atomic claims must be unique nonempty strings')
    asserted = set(texts)
    supported = set().union(*evidence.values()) if evidence else set()
    links = [(c['text'], citation) for c in predicted for citation in c.get('citations', [])]
    if any(len(set(c.get('citations', []))) != len(c.get('citations', [])) for c in predicted):
        raise ValueError('Duplicate citations')
    hits = len(asserted & expected)
    return dict(status='DETERMINISTIC_ATOMIC_CONTRACT', provenance=reference['provenance'],
                answer_correctness=ratio(2 * hits, len(expected) + len(asserted)),
                faithfulness=ratio(len(asserted & supported), len(asserted)),
                citation_accuracy=ratio(sum(t in evidence.get(cid, set()) for t, cid in links), len(links)),
                citation_coverage=ratio(sum(any(t == c['text'] and t in evidence.get(cid, set())
                                                for t, cid in links) for c in predicted), len(predicted)),
                unsupported_claim_rate=ratio(len(asserted - supported), len(asserted)),
                hallucination_rate=None,
                abstention_correct=(prediction.get('refused') == (not expected))
                if type(prediction.get('refused')) is bool else None,
                note='Exact proposition F1/support only; unsupported is not proof of semantic hallucination')


def performance(rows, price=None):
    """Provider usage only; streaming times are relative to request start.

    TTFT=first output TOKEN time. TPOT=(last-first)/(N-1).
    TPS=(N-1)/(last-first seconds), excluding initial wait; nonstreaming null.
    Price requires explicit verified source/date/currency and Decimal rates.
    """
    buckets = {k: [] for k in ('total_ms', 'node_ms', 'tool_ms', 'retrieval_ms', 'reranker_ms', 'ttft_ms', 'tpot_ms', 'tps')}
    inputs = outputs = 0
    usages = 0
    costs = []
    if price is not None:
        if not all(price.get(k) for k in ('source', 'verified_at', 'currency', 'model')):
            raise ValueError('Price verification provenance required')
        rates = [Decimal(str(price[k])) for k in ('input_per_million', 'output_per_million')]
        if any(not r.is_finite() or r < 0 for r in rates):
            raise ValueError('Invalid price')
    for row in rows:
        for key in ('total_ms', 'node_ms', 'tool_ms', 'retrieval_ms', 'reranker_ms'):
            value = row.get(key)
            if value is not None:
                values = value if isinstance(value, list) else [value]
                if any(not finite(v) for v in values):
                    raise ValueError('Invalid duration')
                buckets[key].extend(values)
        usage = row.get('usage')
        if usage is not None:
            if usage.get('source') not in {'PROVIDER_RESPONSE', 'SYNTHETIC_FIXTURE'}:
                raise ValueError('Usage must have explicit provenance')
            a, b = usage.get('input_tokens'), usage.get('output_tokens')
            if any(type(v) is not int or v < 0 for v in (a, b)):
                raise ValueError('Token counts must be nonnegative integers')
            inputs += a
            outputs += b
            usages += 1
            if price is not None:
                if row.get('model') != price['model'] or usage['source'] != 'PROVIDER_RESPONSE':
                    raise ValueError('Price/model or real-usage mismatch')
                costs.append((Decimal(a) * rates[0] + Decimal(b) * rates[1]) / Decimal(1000000))
        times = row.get('token_times_ms', [])
        if times:
            if row.get('stream_timing_source') != 'OUTPUT_TOKEN_TIMESTAMPS' or not usage or usage['source'] != 'PROVIDER_RESPONSE':
                raise ValueError('Actual token timing and provider usage required')
            if (len(times) != usage['output_tokens'] or any(not finite(t) for t in times)
                    or times != sorted(times) or row.get('total_ms') is None or times[-1] > row['total_ms']):
                raise ValueError('Inconsistent token timing')
            buckets['ttft_ms'].append(times[0])
            if len(times) > 1 and times[-1] > times[0]:
                buckets['tpot_ms'].append((times[-1] - times[0]) / (len(times) - 1))
                buckets['tps'].append((len(times) - 1) * 1000 / (times[-1] - times[0]))
    complete = bool(rows) and usages == len(rows)
    known_cost = bool(rows) and len(costs) == len(rows)
    return dict(distributions={k: distribution(v) for k, v in buckets.items()},
                usage=dict(input_tokens=inputs if complete else None, output_tokens=outputs if complete else None,
                           total_tokens=inputs + outputs if complete else None, measured=usages, required=len(rows)),
                cost=dict(total=str(sum(costs)) if known_cost else None,
                          per_request=str(sum(costs) / len(rows)) if known_cost else None,
                          per_100=str(sum(costs) * 100 / len(rows)) if known_cost else None,
                          currency=price['currency'] if price else None, status='MEASURED_USAGE_ESTIMATE' if known_cost else 'UNKNOWN'),
                note='No prices/token estimates or TTFT inferred from nonstreaming responses; quantiles descriptive, no sample-size gate approved')


def agent(cases, observations):
    ids = {c['id'] for c in cases}
    if not cases or len(ids) != len(cases):
        raise ValueError('Unique nonempty Agent dataset required')
    by_id = keyed(observations, ids)
    counts = dict(intent=0, selection=0, completed=0, replanned=0, hitl=0, failure=0, recovery=0)
    attempts = successes = recovery_total = 0
    for c in cases:
        row = by_id.get(c['id'], {})
        counts['intent'] += row.get('intent') == c['intent']
        counts['selection'] += set(row.get('tools', [])) == set(c['tools']) and bool(row)
        counts['completed'] += row.get('status') == 'COMPLETED'
        counts['replanned'] += row.get('replans', 0) > 0
        counts['hitl'] += type(row.get('hitl')) is bool and row['hitl'] == c['hitl']
        counts['failure'] += row.get('status') in {None, 'FAILED', 'ERROR', 'TIMEOUT', 'MISSING', 'CANCELLED'}
        a, b = row.get('tool_attempts', 0), row.get('tool_successes', 0)
        if any(type(v) is not int or v < 0 for v in (a, b)) or b > a:
            raise ValueError('Invalid tool outcomes')
        attempts += a
        successes += b
        if c.get('recovery_expected'):
            recovery_total += 1
            counts['recovery'] += row.get('recovered') is True
    n = len(cases)
    return dict(samples=n, measured=len(by_id), intent_accuracy=counts['intent']/n,
                tool_selection_accuracy=counts['selection']/n, tool_success_rate=ratio(successes, attempts),
                task_completion_rate=counts['completed']/n, replanning_rate=counts['replanned']/n,
                hitl_accuracy=counts['hitl']/n, failure_rate=counts['failure']/n,
                recovery_success_rate=ratio(counts['recovery'], recovery_total), counts=counts,
                note='Task completion means COMPLETED only; safe rejection/cancellation can pass a safety test without completing a task')


def compare(before, after):
    for key in ('dataset_sha256', 'corpus_sha256', 'ks', 'scope', 'metric_version'):
        if before.get(key) is None or before.get(key) != after.get(key):
            return dict(status='BLOCKED', reason=key)
    a, b = before.get('cases', []), after.get('cases', [])
    if {r['id'] for r in a} != {r['id'] for r in b} or len({r['id'] for r in a}) != len(a) or len({r['id'] for r in b}) != len(b):
        return dict(status='BLOCKED', reason='case_ids')
    delta = {}
    for k in before['ks']:
        key = str(k)
        delta[key] = {m: after['retrieval']['at_k'][key][m] - before['retrieval']['at_k'][key][m]
                      if all(r['retrieval']['at_k'][key][m] is not None for r in (before, after)) else None
                      for m in ('recall_at_k', 'precision_at_k', 'mrr', 'ndcg')}
    old = {r['id']: r for r in a}
    return dict(status='COMPARABLE', delta=delta,
                performance_delta={
                    name: after['performance']['distributions'][name]['p95'] - before['performance']['distributions'][name]['p95']
                    if all(r.get('performance', {}).get('distributions', {}).get(name, {}).get('p95') is not None
                           for r in (before, after)) else None
                    for name in ('total_ms', 'node_ms', 'tool_ms', 'retrieval_ms', 'reranker_ms', 'ttft_ms', 'tpot_ms', 'tps')},
                changed_cases=[dict(id=r['id'], before=old[r['id']], after=r) for r in b if old[r['id']] != r],
                gate='REPORT_ONLY; no new thresholds')


def safe_feedback(metrics):
    """Explicit scalar allowlist for a future authorized LangSmith uploader."""
    allowed = {'intent_accuracy', 'tool_selection_accuracy', 'tool_success_rate',
               'task_completion_rate', 'replanning_rate', 'hitl_accuracy', 'failure_rate', 'recovery_success_rate'}
    return {k: float(v) for k, v in metrics.items() if k in allowed and
            type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1}


def report_gate(report, approved_thresholds=None):
    """Observation-only: never blocks business or converts missing data to PASS.

    Optional threshold entries require metric/K/minimum and source provenance.
    Callers must not repurpose a historical scope as a new approved policy.
    """
    findings=[]
    for rule in approved_thresholds or []:
        if not rule.get('source') or not finite(rule.get('minimum')):
            raise ValueError('Approved threshold provenance required')
        value=report['retrieval']['at_k'].get(str(rule['k']),{}).get(rule['metric'])
        findings.append(dict(rule=rule,actual=value,status='NOT RUN' if value is None else
                             'PASS' if value>=rule['minimum'] else 'FAIL'))
    no_answer=report['retrieval']['no_answer']
    if report['retrieval']['errors_or_missing']:
        findings.append(dict(status='FAIL',reason='ERROR/TIMEOUT/MISSING preserved'))
    if no_answer['false_candidate_count']:
        findings.append(dict(status='FAIL',reason='No-answer false candidates',count=no_answer['false_candidate_count']))
    if no_answer['abstention_accuracy'] is None:
        findings.append(dict(status='NOT RUN',reason='Complete refusal observations missing'))
    return dict(mode='REPORT_ONLY',status='PARTIAL',findings=findings,
                note='No statistical sufficiency policy approved; metric checks cannot confer deployment acceptance')
