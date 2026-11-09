"""Synthetic arithmetic contracts. Numbers here are fixtures, not model runs."""
from copy import deepcopy
import math
from uuid import uuid4

import pytest

from app.evaluation.metrics import (agent, answer_quality, compare, distribution,
                                    fingerprint, performance, retrieval, safe_feedback)
from app.rag.evaluation import EvalCase

CASES = [EvalCase('a', 'load rule', frozenset({'right'})), EvalCase('b','no answer')]


def test_retrieval_at_multiple_k_and_frozen_macro_denominators():
    r = retrieval(CASES,[dict(id='a',status='COMPLETED',retrieved=['wrong','right']),
                        dict(id='b',status='COMPLETED',retrieved=[],refused=True)])
    assert r['at_k']['1']['recall_at_k']==0
    assert r['at_k']['3']['recall_at_k']==1
    assert r['at_k']['5']['precision_at_k']==.1
    assert r['at_k']['5']['mrr']==.25
    assert r['at_k']['5']['ndcg']==pytest.approx(1/math.log2(3)/2)
    assert r['no_answer']['abstention_accuracy'] is None


def test_missing_error_is_not_correct_refusal():
    r=retrieval(CASES,[])
    assert r['errors_or_missing']==2 and r['no_answer']['correct_refusal_lower_bound']==0
    assert r['at_k']['5']['recall_at_k']==0


@pytest.mark.parametrize('rows',[
    [dict(id='a',status='COMPLETED',retrieved=['x','x'])],
    [dict(id='a',status='ERROR',retrieved=['x'])],
    [dict(id='a',status='WHAT')],
    [dict(id='a',status='COMPLETED',refused=1)],
    [dict(id='unknown',status='COMPLETED')],
    [dict(id='a',status='MISSING'),dict(id='a',status='MISSING')],
])
def test_invalid_observations_fail_closed(rows):
    with pytest.raises(ValueError):retrieval(CASES,rows)


def test_all_refusal_does_not_hide_answerable_miss():
    r=retrieval(CASES,[dict(id=c.id,status='COMPLETED',retrieved=[],refused=True) for c in CASES])
    assert r['no_answer']['abstention_accuracy']==.5 and r['no_answer']['false_refusals']==1


def test_atomic_claim_reference_and_citation_metrics():
    ref=dict(provenance='synthetic-hand-authored-v1',claims=['load<=limit'],evidence={'c1':['load<=limit']})
    p=dict(claims=[dict(text='load<=limit',citations=['c1']),dict(text='unlimited',citations=['bad'])],refused=False)
    r=answer_quality(ref,p)
    assert r['faithfulness']==r['citation_accuracy']==r['citation_coverage']==.5
    assert r['answer_correctness']==pytest.approx(2/3)
    assert r['unsupported_claim_rate']==.5 and r['hallucination_rate'] is None
    assert answer_quality(ref,dict())['status']=='NOT RUN'


@pytest.mark.parametrize('key',['claims','citations'])
def test_duplicate_answer_claims_or_citations_not_rewarded(key):
    ref=dict(provenance='fixture',claims=['x'],evidence={'c':['x']})
    p=dict(claims=[dict(text='x',citations=['c'])])
    if key=='claims':p['claims']*=2
    else:p['claims'][0]['citations']*=2
    with pytest.raises(ValueError):answer_quality(ref,p)


def test_nonstreaming_and_missing_cost_stay_unknown():
    r=performance([dict(total_ms=100,usage=dict(source='PROVIDER_RESPONSE',input_tokens=9,output_tokens=3))])
    assert r['usage']['total_tokens']==12 and r['cost']['status']=='UNKNOWN'
    assert r['distributions']['ttft_ms']['mean'] is None
    assert performance([])['usage']['total_tokens'] is None


def test_stream_timing_and_verified_decimal_price():
    row=dict(model='test',total_ms=500,usage=dict(source='PROVIDER_RESPONSE',input_tokens=100,output_tokens=3),
             token_times_ms=[100,200,400],stream_timing_source='OUTPUT_TOKEN_TIMESTAMPS')
    price=dict(model='test',source='synthetic-price-contract',verified_at='fixture-date',currency='TEST',input_per_million='2',output_per_million='4')
    r=performance([row],price)
    assert r['distributions']['ttft_ms']['mean']==100
    assert r['distributions']['tpot_ms']['mean']==150
    assert r['distributions']['tps']['mean']==pytest.approx(20/3)
    assert r['cost']['total']=='0.000212'


@pytest.mark.parametrize('changes',[
    dict(token_times_ms=[200,100,300]),dict(token_times_ms=[100]),
    dict(stream_timing_source='SSE_EVENTS'),dict(total_ms=250),
    dict(usage=dict(source='CHARACTER_ESTIMATE',input_tokens=1,output_tokens=3)),
    dict(usage=dict(source='PROVIDER_RESPONSE',input_tokens=True,output_tokens=3)),
])
def test_invalid_timing_usage_rejected(changes):
    row=dict(total_ms=500,usage=dict(source='PROVIDER_RESPONSE',input_tokens=3,output_tokens=3),
             token_times_ms=[100,200,300],stream_timing_source='OUTPUT_TOKEN_TIMESTAMPS')
    with pytest.raises(ValueError):performance([row|changes])


@pytest.mark.parametrize('value',[-1,float('nan'),float('inf'),True])
def test_invalid_latency_rejected(value):
    with pytest.raises(ValueError):distribution([value])


def test_quantiles_and_partial_usage():
    r=performance([dict(total_ms=100),dict(total_ms=500,usage=dict(source='PROVIDER_RESPONSE',input_tokens=1,output_tokens=2))])
    assert r['distributions']['total_ms']['p50']==300
    assert r['distributions']['total_ms']['p95']==480
    assert r['usage']['total_tokens'] is None


def test_agent_safety_success_is_not_task_completion():
    cases=[dict(id='a',intent='WRITE',tools=['cancel_dispatch_plan'],hitl=True),dict(id='b',intent='VEHICLES',tools=['list_vehicles'],hitl=False,recovery_expected=True)]
    rows=[dict(id='a',intent='WRITE',tools=['cancel_dispatch_plan'],hitl=True,status='WAITING_APPROVAL',tool_attempts=0,tool_successes=0),
          dict(id='b',intent='VEHICLES',tools=['list_vehicles'],hitl=False,status='COMPLETED',tool_attempts=1,tool_successes=1,recovered=True)]
    r=agent(cases,rows)
    assert r['intent_accuracy']==r['hitl_accuracy']==r['recovery_success_rate']==1
    assert r['task_completion_rate']==.5
    assert agent(cases,[])['task_completion_rate']==0


@pytest.mark.parametrize('key',['dataset_sha256','corpus_sha256','ks','scope','metric_version'])
def test_cross_dataset_or_scope_comparison_blocked(key):
    r=dict(dataset_sha256='a',corpus_sha256='c',ks=[1,3,5],scope='offline',metric_version='v1')
    changed=deepcopy(r);changed[key]='other'
    assert compare(r,changed)['status']=='BLOCKED'


def test_feedback_strict_allowlist_and_deterministic_fingerprint():
    assert safe_feedback(dict(intent_accuracy=1,password='secret',failure_rate=float('nan')))=={'intent_accuracy':1.0}
    assert fingerprint(dict(a=1,b=2))==fingerprint(dict(b=2,a=1))


def test_comparison_reports_measured_delta_without_inventing_latency():
    rows=[dict(id='a',status='COMPLETED',retrieved=['right']),dict(id='b',status='COMPLETED',retrieved=[])]
    report=dict(dataset_sha256='same',corpus_sha256='same',ks=[1,3,5],scope='offline',
                metric_version='v1',cases=rows,retrieval=retrieval(CASES,rows),
                performance=performance([dict(total_ms=100)]))
    changed=deepcopy(report)
    changed['performance']=performance([dict(total_ms=150)])
    result=compare(report,changed)
    assert result['delta']['5']['mrr']==0
    assert result['performance_delta']['total_ms']==50
    assert result['performance_delta']['ttft_ms'] is None


def test_new_graph_nodes_traced_without_raw_inputs():
    from app.agent.observability import SafeAgentCallback
    class Sender:
        def __init__(self):self.events=[]
        def submit(self,operation,payload):self.events.append(payload)
    sender=Sender();cb=SafeAgentCallback(sender,'logistics-agent-test','test','chat')
    for name in ('intent','planner','validate_plan','analyze','decide','replan','finish','list_drivers'):
        rid=uuid4()
        cb.on_chain_start({},dict(password='SENSITIVE'),run_id=rid,name=name)
        cb.on_chain_end(dict(password='SENSITIVE'),run_id=rid)
    assert all(e['inputs']=={} for e in sender.events if 'inputs' in e)
    assert 'SENSITIVE' not in str(sender.events)
    assert 'planner' in {e['name'] for e in sender.events}


def test_report_gate_keeps_errors_refusal_and_threshold_provenance():
    from app.evaluation.metrics import report_gate
    report={'retrieval':retrieval(CASES,[])}
    gate=report_gate(report)
    assert gate['mode']=='REPORT_ONLY' and gate['status']=='PARTIAL'
    assert any(x['status']=='FAIL' for x in gate['findings'])
    with pytest.raises(ValueError):
        report_gate(report,[dict(k=5,metric='recall_at_k',minimum=.9)])
