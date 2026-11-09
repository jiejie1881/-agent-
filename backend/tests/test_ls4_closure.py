"""Synthetic contract tests; never semantic or cloud acceptance."""
from copy import deepcopy
import pytest
from app.evaluation.closure import answer_outcomes,trace_quality,admission,judge_result

CASES=[dict(id='answerable',answerable=True),dict(id='unknown',answerable=False)]


def row(key,refused,**kw):
    return dict(id=key,status='COMPLETED',review_kind='OFFLINE_FIXTURE',basis='synthetic-hand-authored',refused=refused,**kw)


def test_missing_answers_cannot_pass_zero_false_answers():
    result=answer_outcomes(CASES,[])
    assert result['unknown']==2 and result['no_answer_false_answer_rate'] is None


def test_bidirectional_answer_refusal_and_citations():
    result=answer_outcomes(CASES,[row('answerable',False,citation_outcomes=[True]),row('unknown',True)])
    assert result['abstention_accuracy']==result['citation_accuracy']==1
    assert result['no_answer_false_answer_rate']==0
    all_refuse=answer_outcomes(CASES,[row(c['id'],True) for c in CASES])
    assert all_refuse['answerable_false_refusal_rate']==1


def test_false_answer_and_invalid_citation_not_hidden():
    r=answer_outcomes(CASES,[row('answerable',False,citation_outcomes=[False],invalid_citation=True),row('unknown',False)])
    assert r['false_answers']==1 and r['invalid_citation_count']==1 and r['citation_accuracy']==0


@pytest.mark.parametrize('status',['ERROR','TIMEOUT','MISSING'])
def test_failed_observation_stays_unknown(status):
    r=answer_outcomes(CASES,[dict(id='unknown',status=status)])
    assert r['unknown']==2 and r['abstention_accuracy'] is None


def test_trace_tree_missing_node_parent_terminal_and_cycle():
    runs=[dict(id='r',parent_id=None,name='agent',status='COMPLETED',start_ms=0,end_ms=3),
          dict(id='c',parent_id='r',name='tools',status='ERROR',start_ms=1,end_ms=2)]
    assert trace_quality(runs,['agent','tools'])['status']=='PASS'
    assert trace_quality(runs,['retriever'])['status']=='BLOCKED'
    broken=deepcopy(runs);broken[1]['parent_id']='missing'
    assert trace_quality(broken,[])['status']=='BLOCKED'
    broken[1]['parent_id']='c'
    assert trace_quality(broken,[])['status']=='BLOCKED'


def test_original_completion_target_not_replaced_by_expected_safety_behavior():
    agent=dict(intent_accuracy=1,tool_selection_accuracy=1,task_completion_rate=.6)
    answers=answer_outcomes(CASES,[row('answerable',False,citation_outcomes=[True]),row('unknown',True)])
    result=admission(agent,answers,dict(status='PASS',run_count=1),unauthorized_calls=0)
    assert result['status']=='BLOCKED'
    assert next(c for c in result['checks'] if c['name']=='task_completion_target_90')['status']=='FAIL'
    assert admission(agent,answers,dict(status='PASS',run_count=1),dataset_matches=False)['status']=='BLOCKED'


@pytest.mark.parametrize('value',[{},dict(correctness=True,faithfulness=1,citation_accuracy=1,reason_codes=[]),
 dict(correctness=float('nan'),faithfulness=1,citation_accuracy=1,reason_codes=[]),
 dict(correctness=1,faithfulness=1,citation_accuracy=2,reason_codes=[])])
def test_invalid_judge_results_rejected(value):
    with pytest.raises(ValueError):judge_result(value)


def test_judge_remains_exploratory():
    assert judge_result(dict(correctness=1,faithfulness=1,citation_accuracy=1,reason_codes=[]))['status']=='EXPLORATORY_NOT_CALIBRATED'


def test_one_good_link_cannot_hide_another_uncited_unsupported_answer():
    cases=CASES+[dict(id='second',answerable=True)]
    answers=answer_outcomes(cases,[row('answerable',False,citation_outcomes=[True],evidence_sufficient=True),
                                 row('unknown',True),row('second',False)])
    assert answers['citation_accuracy']==1
    gate=admission(dict(intent_accuracy=1,tool_selection_accuracy=1,task_completion_rate=1),
                   answers,dict(status='PASS',run_count=4),unauthorized_calls=0)
    assert gate['status']=='BLOCKED'
    assert answers['missing_citations']==answers['unsupported_answers']==1
