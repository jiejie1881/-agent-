"""Refusal behavior fixtures are not real semantic answer-quality evidence."""
import pytest

from app.rag.evaluation import EvalCase, aggregate
from app.rag.evaluation_pipeline import Observation, evaluate_observations

CASES = [EvalCase('answerable','synthetic rule',frozenset({'rule'})),
         EvalCase('negative','synthetic no answer',frozenset())]


def evaluate(rows, cases=CASES):
    return evaluate_observations(cases, rows, k=4, dataset_sha256='synthetic', corpus_version='v1',
                                 model_version='not-a-model', strategy='hybrid', scope='OFFLINE_FIXTURE')


def test_false_refusal_and_false_acceptance_are_separate_from_recall():
    rows = [Observation('answerable', retrieved=('rule',), refused=True),
            Observation('negative', retrieved=('irrelevant',), refused=False)]
    r = evaluate(rows)
    assert r['retrieval'] == aggregate(CASES, {'answerable':['rule'],'negative':['irrelevant']}, 4).as_dict()
    assert r['retrieval']['recall_at_k'] == 1
    refusal = r['refusal']
    assert refusal['answerable_false_refusal_questions'] == 1
    assert refusal['answerable_false_refusal_rate'] == 1
    assert refusal['unanswerable_nonrefusal_questions'] == 1
    assert refusal['unanswerable_nonrefusal_rate'] == 1
    assert r['answer_quality']['answer_correctness']['value'] is None


def test_all_refusal_does_not_open_a_gate_even_with_perfect_candidate_recall():
    r = evaluate([Observation('answerable', retrieved=('rule',), refused=True), Observation('negative', refused=True)])
    assert r['refusal']['all_refused'] is True
    assert r['refusal']['answerable_false_refusal_rate'] == 1
    assert r['refusal']['correct_refusal_rate'] == 1
    assert r['status'] == 'PARTIAL'


@pytest.mark.parametrize('status', ['ERROR','TIMEOUT','MISSING'])
def test_incomplete_predictions_never_imply_zero_error_or_perfect_refusal(status):
    r = evaluate([Observation('answerable', status=status), Observation('negative', status=status)])
    assert r['refusal']['answerable_false_refusal_rate'] is None
    assert r['refusal']['unanswerable_nonrefusal_rate'] is None
    assert r['refusal']['all_refused'] is None
    assert r['reliability']['error_rate'] == 1


def test_unknown_behavior_and_zero_denominator_stay_unknown():
    assert evaluate([Observation('answerable'),Observation('negative')])['refusal']['all_refused'] is None
    for cases in (CASES[:1], CASES[1:]):
        r = evaluate([Observation(c.id, refused=True) for c in cases], cases)
        assert r['refusal']['all_refused'] is None  # Missing one class cannot pass balanced acceptance.
        if not cases[0].answerable:
            assert r['refusal']['answerable_false_refusal_rate'] is None
        else:
            assert r['refusal']['unanswerable_nonrefusal_rate'] is None


def test_both_classes_measured_reports_behavior_not_correctness():
    r = evaluate([Observation('answerable',refused=False),Observation('negative',refused=True)])
    assert r['refusal']['all_refused'] is False
    assert r['refusal']['answerable_false_refusal_rate'] == 0
    assert r['refusal']['unanswerable_nonrefusal_rate'] == 0
    assert r['answer_quality']['status'] == 'NOT RUN'
    assert r['status'] == 'PARTIAL'
