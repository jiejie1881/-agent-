import json
import os
from pathlib import Path

import pytest

from app.rag.evaluation import EvalCase, aggregate
from replay.frozen_replay import METHODS, replay


@pytest.fixture(scope='module')
def frozen_results():
    first, second = replay('run1'), replay('run2')
    assert first == second
    root = Path(os.environ['RAG_BATCH1_WORKSPACE'])
    for name,value in [('run1',first),('run2',second)]:
        with (root/(name+'-replay.json')).open('x',encoding='utf-8') as f:
            json.dump(value,f,ensure_ascii=False,indent=2)
    return first


@pytest.mark.parametrize('method', METHODS)
@pytest.mark.parametrize('dataset', ['development','fixed'])
def test_metrics_match_actual_shared_implementation(frozen_results, method,dataset):
    rows = [r for r in frozen_results['rows'] if r['dataset']==dataset]
    cases = [EvalCase(r['id'],r['query'],frozenset(r['expected'])) for r in rows]
    measured = aggregate(cases,{r['id']:r['methods'][method]['top4'] for r in rows},4)
    expected = frozen_results['summary'][dataset][method]
    assert measured.recall_at_k == pytest.approx(expected['recall'])
    assert measured.precision_at_k == pytest.approx(expected['precision'])
    assert measured.mrr == pytest.approx(expected['mrr'])
    assert measured.ndcg == pytest.approx(expected['ndcg'])


@pytest.mark.parametrize('question', ['h04','h10','h05','h06','h07','q13'])
def test_focus_failures_and_negative_examples_retained(frozen_results,question):
    row = next(r for r in frozen_results['rows'] if r['id']==question)
    methods = row['methods']
    if question=='h04':
        assert methods['R']['metrics']['recall']==.5
        assert methods['W2']['metrics']['recall']==methods['L2']['metrics']['recall']==1
    elif question=='h10':
        assert methods['B']['metrics']['recall']==1
        assert methods['R']['metrics']['recall']==methods['W2']['metrics']['recall']==methods['L2']['metrics']['recall']==.5
    elif question=='h05':
        assert all(not methods[m]['top4'] for m in METHODS)
    elif question in {'h06','h07'}:
        assert all(methods[m]['negative_with_candidates'] for m in METHODS)
    else:
        assert methods['W2']['metrics']['ndcg'] < methods['R']['metrics']['ndcg']
        assert methods['L2']['metrics']['ndcg'] < methods['R']['metrics']['ndcg']


def test_alternatives_do_not_meet_original_thresholds(frozen_results):
    for method in ('R','W2','L2'):
        values = frozen_results['summary']['fixed'][method]
        assert values['recall']<.95 and values['ndcg']<.65
    assert frozen_results['records_checked']==126
    assert len(frozen_results['rows'])==42
