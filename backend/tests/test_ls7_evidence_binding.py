import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.rag.answerability import Status,Basis,EvidenceSpan,ServerAssessment,assess
from app.rag.evidence_binding import BoundChunk,FactKind,assess_bound,read_tool_hint,shadow_observation
from tests.test_rag_answerability import supported
from tests.test_ls5_no_evidence import scenario


def binding(value=None,**changes):
    value=value or supported();s=value.spans[0]
    return BoundChunk(s.chunk_id,'synthetic-rules',s.document_version,s.source_text,FactKind.RULE,True,True,**changes)


def test_verified_exact_rule_support_is_retained():
    value=supported()
    assert assess_bound(value,FactKind.RULE,(binding(value),)).status is Status.SUPPORTED


@pytest.mark.parametrize('change,status',[
    ({'chunk_id':'not-returned'},Status.INSUFFICIENT_EVIDENCE),
    ({'version':'other'},Status.CONFLICT),
    ({'text':'不同正文'},Status.CONFLICT),
    ({'authorized':False},Status.PERMISSION_DENIED),
    ({'current':False},Status.INSUFFICIENT_EVIDENCE),
    ({'kind':FactKind.STATIC},Status.CONDITION_MISMATCH),
])
def test_foreign_stale_unbound_or_wrong_scope_evidence_cannot_support(change,status):
    value=supported();chunk=replace(binding(value),**change)
    assert assess_bound(value,FactKind.RULE,(chunk,)).status is status


def test_conflicting_identity_and_duplicate_count_cannot_inflate_support():
    value=supported();chunk=binding(value)
    assert assess_bound(value,FactKind.RULE,(chunk,chunk)).may_answer
    assert assess_bound(value,FactKind.RULE,(chunk,replace(chunk,version='v2'))).status is Status.CONFLICT
    assert assess_bound(replace(value,candidates=2),FactKind.RULE,(chunk,chunk)).status is Status.INSUFFICIENT_EVIDENCE


def test_two_independent_bound_spans_can_jointly_support_required_claims():
    value=supported();first=binding(value);text='同一配送需求不能重复分配。'
    span=EvidenceSpan('v2','second',text,0,len(text),frozenset({'unique_demand'}))
    value=replace(value,candidates=2,required_claims=value.required_claims|{'unique_demand'},spans=value.spans+(span,))
    second=BoundChunk('second','synthetic-second','v2',text,FactKind.RULE,True,True)
    assert assess_bound(value,FactKind.RULE,(first,second)).may_answer


@pytest.mark.parametrize('kind',[FactKind.LIVE_ORDER,FactKind.LIVE_VEHICLE,FactKind.LIVE_DELIVERY])
def test_rules_do_not_prove_instance_facts_even_with_high_retrieval_scores(kind):
    value=supported();chunk=binding(value,scores=(('score',1.),('rrf_score',999.)))
    decision=assess_bound(value,kind,(chunk,))
    assert not decision.may_answer and decision.status is Status.CAPABILITY_UNAVAILABLE


def test_missing_arrival_tool_not_invented_but_verified_read_capability_can_route():
    value=replace(supported(),required_business_capability='actual_arrival_time',approved_business_capabilities=frozenset({'actual_arrival_time'}),business_authorized=True)
    assert assess_bound(value,FactKind.LIVE_DELIVERY,(binding(value),)).status is Status.CAPABILITY_UNAVAILABLE
    value=replace(value,required_business_capability='vehicle_operating_status',approved_business_capabilities=frozenset({'vehicle_operating_status'}))
    result=assess_bound(value,FactKind.LIVE_VEHICLE,(binding(value),))
    assert result.status is Status.ROUTE_BUSINESS and not result.may_answer


def test_procedure_and_static_fact_types_not_interchangeable():
    value=supported()
    assert assess_bound(value,FactKind.STATIC,(binding(value),)).status is Status.CONDITION_MISMATCH
    assert assess_bound(value,FactKind.UNKNOWN,(binding(value),)).status is Status.INSUFFICIENT_EVIDENCE


def test_scores_cannot_supply_missing_semantic_assessment():
    value=replace(supported(),spans=(),support_basis=Basis.UNKNOWN)
    assert assess_bound(value,FactKind.RULE,(binding(),)).status is Status.INSUFFICIENT_EVIDENCE
    with pytest.raises(TypeError):assess_bound({},FactKind.RULE,())


def test_read_hint_uses_actual_registered_read_catalogue_and_authorization(client,session,resources):
    from app.api.agent_dependencies import build_task_registry
    from tests.test_agent_phase2 import current_admin
    registry,executors=build_task_registry(session)
    actor=current_admin(session)
    assert read_tool_hint('vehicle_operating_status',registry,actor)=='list_vehicles'
    assert read_tool_hint('actual_arrival_time',registry,actor) is None
    assert read_tool_hint('vehicle_operating_status',registry,SimpleNamespace(is_active=False)) is None
    assert read_tool_hint('vehicle_operating_status',registry,resources['driver']) is None
    from app.agent.tool_execution import AgentToolContext
    data=asyncio.run(executors.execute('list_vehicles',registry.validate_arguments('list_vehicles',{}),AgentToolContext(current_user=actor))).data
    actual=next(v for v in data['items'] if v['id']==resources['vehicle'].id)
    status=resources['vehicle'].operating_status
    assert actual['operating_status']==getattr(status,'value',status)


@pytest.fixture(name='resources')
def real_resources(session):
    from tests.test_agent_dispatch_foundation import resources
    return resources.__wrapped__(session)


@pytest.mark.parametrize('mode',['off','shadow'])
def test_shared_model_shadow_does_not_change_legacy_answer_or_call_count(mode,monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(),'rag_evidence_gate_mode',mode)
    workflow,model,state=scenario(hits=[dict(chunk_id='a'*64,document_id='rules',index_version='v1',content='车辆载重规则。',document_type='dispatch_rule')])
    next(iter(state['read_results'].values()))['data']['query']='车辆载重规则'
    result=asyncio.run(workflow.model(state))
    assert result['content']=='肯定可以，无须任何限制。' and model.calls==1
    if mode=='shadow':
        assert result['evidence_shadow'][0]['status']=='INSUFFICIENT_EVIDENCE'
        assert 'content' not in str(result['evidence_shadow'])
    else:assert 'evidence_shadow' not in result


def test_shadow_observer_error_never_retries_or_changes_business(monkeypatch):
    import app.agent.graph_workflow as graph
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(),'rag_evidence_gate_mode','shadow')
    def fail(*args):raise RuntimeError('synthetic-only-observer-error')
    monkeypatch.setattr(graph,'shadow_observation',fail)
    workflow,model,state=scenario(hits=[dict(chunk_id='a'*64)])
    result=asyncio.run(workflow.model(state))
    assert model.calls==1 and result['evidence_shadow']==[dict(mode='shadow',status='OBSERVER_ERROR')]


def test_shadow_permission_failure_is_not_swallowed(monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(),'rag_evidence_gate_mode','shadow')
    workflow,model,state=scenario(revoked=True)
    with pytest.raises(ValueError):asyncio.run(workflow.model(state))
    assert model.calls==0


def test_real_governed_tool_graph_persists_shadow_in_own_checkpoint(graph_context,monkeypatch):
    import json,os
    from pathlib import Path
    from app.core.config import get_settings
    from app.agent.model_types import AgentModelResponse,AgentToolCall
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    monkeypatch.setattr(get_settings(),'rag_evidence_gate_mode','shadow')
    g=graph_context
    class Model:
        calls=0
        async def chat(self,*args):
            self.calls+=1
            if self.calls==1:return AgentModelResponse(tool_calls=(AgentToolCall(id='synthetic',name='search_knowledge_base',arguments={'query':'SYNTHETIC_RESTRICTED_RULE','knowledge_base_id':g.base.id}),))
            return AgentModelResponse(content=f'司机请假需确认代班 [{g.rag.last_candidates[0].chunk_id}]')
    model=Model();g.service.model_client=model
    async def run():
        result=await g.service.chat('物流规则',g.context)
        async with AsyncSqliteSaver.from_conn_string(str(g.service.graph_store.path)) as saver:
            rows=[r async for r in saver.alist(None,limit=1)]
        return result,rows[0].checkpoint['channel_values']['evidence_shadow']
    result,shadow=asyncio.run(run())
    assert model.calls==2 and result.tool_calls_count==1
    assert shadow and shadow[0]['mode']=='shadow' and not shadow[0]['may_answer']
    assert '司机' not in str(shadow) and 'password' not in str(shadow)
    folder=os.environ.get('LS2_AGENT_OUTPUT')
    if folder:
        with (Path(folder)/'shadow-checkpoint.json').open('x',encoding='utf-8') as f:
            json.dump(dict(model='SCRIPTED',calls=model.calls,tool_calls=1,shadow=shadow),f,ensure_ascii=False,indent=2)


def test_missing_bound_semantic_evidence_blocks_otherwise_perfect_report():
    from app.evaluation.closure import admission
    result=admission(dict(intent_accuracy=1,tool_selection_accuracy=1,task_completion_rate=1),
        dict(no_answer_false_answer_rate=0,citation_accuracy=1,reviewed=10,invalid_citation_count=0,
             unsupported_answers=0,missing_citations=0),dict(status='PASS',run_count=4),unauthorized_calls=0,
        real_model_result=dict(scope='REAL_MODEL',usage_source='PROVIDER_RESPONSE',model='synthetic-contract',
                               evidence_sha256='a'*64,successful_requests=1))
    assert result['status']=='BLOCKED'
    assert next(c for c in result['checks'] if c['name']=='bound_semantic_evidence')['status']=='BLOCKED'


def test_version_fingerprint_detects_graph_changes_without_task_plan_change(tmp_path,monkeypatch):
    from pathlib import Path
    import sys
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'tools'))
    from evaluate_ls4 import agent_source_version,AGENT_SOURCE_FILES
    for name in AGENT_SOURCE_FILES:
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('initial',encoding='utf-8')
    first=agent_source_version(tmp_path)
    (tmp_path/'backend/app/agent/graph_workflow.py').write_text('changed-node',encoding='utf-8')
    assert agent_source_version(tmp_path)!=first


from tests.test_agent_knowledge_cache_authorization import graph_context,private_governance  # noqa: E402,F401
