"""Local MOCK judge/LLM contracts; not independent semantic quality labels."""
import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from app.rag.answer_contract import snapshot, BusinessRequest, canonical
from app.rag.semantic_judge import (EvidenceState, JudgeOpinion, MockSemanticJudge, SemanticJudgePipeline)
from app.rag.semantic_contract import (IsolatedSemanticContract, response_example, validate_answer, OutputContractError)
from app.agent.model_types import AgentModelResponse, AgentToolCall
from tests.test_ls8_answer_contract import setup as old_setup, supported, HIT, TEXT


@pytest.fixture(autouse=True)
def isolated_ls9(monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), 'rag_semantic_gate_mode', 'isolated')


def pipeline(state=EvidenceState.SUPPORTED, proof_factory=supported):
    return SemanticJudgePipeline(MockSemanticJudge(state), MockSemanticJudge(state, proof_factory=proof_factory),
                                 MockSemanticJudge(state))


def setup(responses=None, judge=None, **kwargs):
    workflow, _, state = old_setup(**kwargs)
    contract = IsolatedSemanticContract(judge or pipeline())
    context = snapshot(state)
    valid = AgentModelResponse(content=canonical(response_example(context, supported(context))))
    class Model:
        calls=0
        messages=[]
        async def chat(self, messages, tools):
            assert tools == []
            self.messages.append(messages)
            result = (responses or [valid])[min(self.calls, len(responses or [valid])-1)]
            self.calls+=1
            if isinstance(result, Exception): raise result
            return result
    model=Model()
    workflow.service.model_client=model
    workflow.service.answer_contract=contract
    return workflow, model, state, valid


def run(workflow, state):
    return asyncio.run(workflow.model(state))


def test_supported_response_has_claims_bound_citations_and_auditable_versions():
    workflow, model, state, _ = setup()
    result=run(workflow,state)
    assert result['answerability']['status']=='ANSWERABLE' and TEXT in result['content']
    assert result['answer_response']['response_version']=='ls9-answer-v1'
    trace=result['semantic_decision']['traces']
    assert len(trace)==3 and all(t['version']=='MOCK-NOT-SEMANTIC-v1' for t in trace)
    assert all(t['evidence_versions'][0][1]=='synthetic-v1' for t in trace) and model.calls==1


@pytest.mark.parametrize('label', [EvidenceState.IRRELEVANT, EvidenceState.INSUFFICIENT,
    EvidenceState.CONTRADICTORY, EvidenceState.UNKNOWN])
def test_negative_and_unknown_judge_states_do_not_call_model(label):
    workflow, model, state, _ = setup(judge=pipeline(label))
    result=run(workflow,state)
    assert result['answerability']['status']==label.value and model.calls==0
    assert result['semantic_decision']['outcome']=='DECIDED'


@pytest.mark.parametrize('bad', ['not-json', '{}', 'null', '{"status":"ANSWER","status":"REFUSED"}',
    canonical(dict(response_version='ls9-answer-v1',status='REFUSED',answer='',claims=[],citations=[],
                   refusal_reason='模型认为无答案',evidence_refs=[]))])
def test_format_and_model_refusal_repair_once_without_changing_evidence(bad):
    workflow, model, state, valid = setup()
    model.chat = repairing = _sequence([AgentModelResponse(content=bad), valid], model)
    before=snapshot(state).sha256
    result=run(workflow,state)
    assert result['answerability']['status']=='ANSWERABLE' and model.calls==2
    assert len(result['semantic_decision']['attempts'])==2
    assert snapshot(state).sha256==before
    assert '证据范围不变' in model.messages[-1][-1].content
    assert callable(repairing)


def _sequence(responses, model):
    async def chat(messages, tools):
        assert tools==[]
        model.messages.append(list(messages))
        result=responses[min(model.calls,len(responses)-1)]
        model.calls+=1
        return result
    return chat


def test_persistent_invalid_output_is_system_error_not_a_no_answer_label():
    workflow, model, state, _ = setup(responses=[AgentModelResponse(content='随意肯定，无需限制。')])
    result=run(workflow,state)
    assert result['answerability']['status']=='OUTPUT_ERROR' and model.calls==2
    assert result['semantic_decision']['evidence_state']=='SUPPORTED'
    assert '不是知识库无答案结论' in result['content']
    assert result['answer_response']=={}


def test_retry_count_is_bounded_and_can_be_disabled():
    for value in (-1,2,True):
        with pytest.raises(ValueError):IsolatedSemanticContract(pipeline(),repair_attempts=value)
    workflow, model, state, _=setup(responses=[AgentModelResponse(content='bad')])
    workflow.service.answer_contract.repair_attempts=0
    assert run(workflow,state)['answerability']['status']=='OUTPUT_ERROR' and model.calls==1


@pytest.mark.parametrize('tamper,code', [('source','CITATION_BINDING_INVALID'),('version','CITATION_BINDING_INVALID'),
    ('id','CITATION_BINDING_INVALID'),('quote','CLAIM_SUPPORT_INVALID'),('claim','CLAIM_SUPPORT_INVALID'),
    ('answer','UNSUPPORTED_ANSWER_TEXT'),('hash','EVIDENCE_REFS_INVALID'),('missing','CITATION_MISSING'),
    ('extra','SCHEMA_INVALID'),('refusal','MODEL_REFUSAL_WITH_SUPPORT'),('duplicate-ref','EVIDENCE_REFS_INVALID')])
def test_schema_claim_and_citation_security(tamper,code):
    workflow, _, state, valid=setup()
    value=json.loads(valid.content)
    if tamper in ('source','version','id'):
        value['citations'][0][{'source':'document_id','version':'document_version','id':'chunk_id'}[tamper]]='foreign'
    elif tamper=='quote':value['citations'][0]['quote']='删去了禁止和限定条件'
    elif tamper=='claim':value['claims'][0]['text']='允许超载';value['answer']='允许超载'
    elif tamper=='answer':value['answer']+=' 允许超载'
    elif tamper=='hash':value['evidence_refs'][0]['body_sha256']='0'*64
    elif tamper=='missing':value['citations']=[]
    elif tamper=='extra':value['answerable']=True
    elif tamper=='refusal':value['status']='REFUSED'
    elif tamper=='duplicate-ref':value['evidence_refs']*=2
    context=snapshot(state)
    with pytest.raises(OutputContractError) as error:validate_answer(canonical(value),context,supported(context))
    assert error.value.code==code


@pytest.mark.parametrize('bad', ['raise','timeout','dict','state','foreign','no-proof'])
def test_judge_failures_are_errors_not_correct_refusals(bad):
    class BadJudge:
        async def judge(self, context):
            if bad=='raise':raise RuntimeError('SECRET_MUST_NOT_APPEAR')
            if bad=='timeout':await asyncio.sleep(.1)
            if bad=='dict':return dict(answerable=True)
            if bad=='state':return JudgeOpinion('SUPPORTED',context.sha256,'bad',())
            if bad=='foreign':return JudgeOpinion(EvidenceState.SUPPORTED,'0'*64,'bad',())
            return JudgeOpinion(EvidenceState.SUPPORTED,context.sha256,'no-proof',())
    judge=SemanticJudgePipeline(MockSemanticJudge(EvidenceState.SUPPORTED), BadJudge(),
                               MockSemanticJudge(EvidenceState.SUPPORTED),timeout_seconds=.01)
    workflow, model, state, _=setup(judge=judge)
    result=run(workflow,state)
    assert result['answerability']['status']=='JUDGE_ERROR' and model.calls==0
    assert result['semantic_decision']['outcome']=='JUDGE_ERROR' and 'SECRET_MUST_NOT_APPEAR' not in str(result)


def test_cancellation_propagates_without_repair():
    class Cancel:
        async def judge(self, context):raise asyncio.CancelledError()
    workflow, model, state, _=setup(judge=SemanticJudgePipeline(Cancel(),Cancel(),Cancel()))
    with pytest.raises(asyncio.CancelledError):run(workflow,state)
    assert model.calls==0


@pytest.mark.parametrize('change',['owner','conversation','question','rewrite','body','version'])
def test_judge_positive_proof_cannot_replay_for_another_context(change):
    workflow,model,state,_=setup()
    proof=supported(snapshot(state))
    if change=='owner':state['user_id']=4;workflow.context.current_user.id=4
    elif change=='conversation':state['conversation_id']=7;workflow.context.conversation_id=7
    elif change=='question':state['messages'][-1]['content']+='另一个对象'
    else:
        data=next(iter(state['read_results'].values()))['data']
        if change=='rewrite':data['query']+='改写变化'
        else:data['results'][0][{'body':'content','version':'index_version'}[change]]+='changed'
    workflow.service.answer_contract.pipeline=pipeline(proof_factory=lambda _:proof)
    assert run(workflow,state)['answerability']['status']=='BINDING_ERROR' and model.calls==0


def test_unknown_consistency_is_not_treated_as_proven_no_conflict():
    judge=SemanticJudgePipeline(MockSemanticJudge(EvidenceState.SUPPORTED),
        MockSemanticJudge(EvidenceState.SUPPORTED,proof_factory=supported),MockSemanticJudge(EvidenceState.UNKNOWN))
    workflow,model,state,_=setup(judge=judge)
    assert run(workflow,state)['answerability']['status']=='UNKNOWN' and model.calls==0


def test_mutation_during_repair_stops_without_unrestricted_fallback():
    workflow,model,state,valid=setup()
    async def chat(messages,tools):
        model.calls+=1
        if model.calls==1:return AgentModelResponse(content='bad')
        next(iter(state['read_results'].values()))['data']['results'][0]['index_version']='changed'
        return valid
    model.chat=chat
    assert run(workflow,state)['answerability']['status']=='BINDING_ERROR' and model.calls==2


def test_provider_failure_is_not_refusal_and_never_retried():
    workflow,model,state,_=setup(responses=[TimeoutError('SECRET')])
    result=run(workflow,state)
    assert result['answerability']['status']=='MODEL_ERROR' and model.calls==1
    assert 'SECRET' not in str(result)


def test_error_replay_clears_previous_accepted_payload():
    workflow,model,state,_=setup()
    accepted=run(workflow,state)
    state={**state,**accepted}
    assert state['answer_response']['status']=='ANSWER'
    model.chat=_sequence([AgentModelResponse(content='bad')],model)
    result=run(workflow,state)
    assert result['answerability']['status']=='OUTPUT_ERROR' and result['answer_response']=={}


def test_waiting_for_new_tools_cannot_keep_old_answer_payload():
    workflow,model,state,_=setup()
    state['read_results']={};state['answer_response']={'status':'ANSWER'}
    model.chat=_sequence([AgentModelResponse(tool_calls=(AgentToolCall(id='search',name='search_knowledge_base',
        arguments={'query':'车辆规则'}),))],model)
    result=run(workflow,state)
    assert result['answer_response']=={} and result['semantic_decision']['outcome']=='AWAITING_TOOLS'


def test_flag_disabled_during_generation_stops_output(monkeypatch):
    from app.core.config import get_settings
    workflow,model,state,valid=setup()
    async def chat(*args):
        model.calls+=1
        monkeypatch.setattr(get_settings(),'rag_semantic_gate_mode','off')
        return valid
    model.chat=chat
    result=run(workflow,state)
    assert result['answerability']['status']=='POLICY_DISABLED' and result['answer_response']=={} and model.calls==1


def test_feature_flag_is_explicit_and_old_defaults_remain(monkeypatch,tmp_path):
    from app.core.config import get_settings,Settings
    settings=get_settings()
    assert Settings.model_fields['rag_semantic_gate_mode'].default=='off'
    assert settings.rag_reference_policy=='legacy' and settings.rag_evidence_gate_mode=='off'
    contract=IsolatedSemanticContract(pipeline())
    monkeypatch.setattr(settings,'app_environment','test')
    monkeypatch.setattr(settings,'rag_semantic_gate_mode','off')
    with pytest.raises(ValueError):contract.validate_installation(tmp_path/'c.sqlite')
    workflow,model,state,_=setup()
    assert run(workflow,state)['answerability']['status']=='POLICY_DISABLED' and model.calls==0


def test_governed_graph_persists_schema_judge_trace_and_blocks_revoked_replay(graph_context):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from app.rag.evidence_binding import FactKind
    from app.agent.exceptions import AgentToolExecutionError
    g=graph_context
    g.service.answer_contract=IsolatedSemanticContract(pipeline(proof_factory=lambda c:replace(supported(c),kind=FactKind.PROCEDURE)))
    class Model:
        calls=0
        async def chat(self,messages,tools):
            self.calls+=1
            if self.calls==1:return AgentModelResponse(tool_calls=(AgentToolCall(id='ls9-real-tool',name='search_knowledge_base',
                arguments=dict(query='SYNTHETIC_RESTRICTED_RULE',knowledge_base_id=g.base.id)),))
            if self.calls==2:return AgentModelResponse(content='bad JSON')
            # Exact server contract in prompt, not frozen labels.
            value=messages[-2].content.split('示例：',1)[1]
            return AgentModelResponse(content=value)
    g.service.model_client=Model()
    async def execute():
        result=await g.service.chat('司机请假怎么处理？',g.context)
        async with AsyncSqliteSaver.from_conn_string(str(g.service.graph_store.path)) as saver:
            rows=[r async for r in saver.alist(None,limit=1)]
        return result,rows[0].checkpoint['channel_values']
    result,state=asyncio.run(execute())
    assert result.tool_calls_count==1 and '司机请假' in result.content and g.service.model_client.calls==3
    assert state['semantic_decision']['policy']=='ls9-semantic-v1'
    assert state['answer_response']['status']=='ANSWER' and len(state['semantic_decision']['attempts'])==2
    g.revoke()
    with pytest.raises(AgentToolExecutionError):run(g.workflow,state)


def test_closed_business_route_uses_real_tool_and_cannot_supply_arrival_time(client,session,resources,tmp_path,monkeypatch):
    from app.agent.agent_service import AgentService
    from app.agent.tool_execution import AgentToolContext
    from app.api.agent_dependencies import build_task_registry
    from app.core.config import get_settings
    from tests.test_agent_phase2 import current_admin
    monkeypatch.setattr(get_settings(),'app_environment','test')
    registry,executors=build_task_registry(session)
    contract=IsolatedSemanticContract(pipeline(EvidenceState.UNKNOWN),business_resolver=lambda c:
        BusinessRequest(c.sha256,'vehicle_operating_status','{}',resources['vehicle'].id))
    service=AgentService(SimpleNamespace(),registry,executors,checkpoint_path=tmp_path/'ls9.sqlite',answer_contract=contract)
    context=AgentToolContext(current_user=current_admin(session))
    result=asyncio.run(service.chat('当前车辆状态',context))
    assert result.used_tools==('list_vehicles',)
    assert json.loads(result.content.split('：',1)[1])['operating_status']==resources['vehicle'].operating_status
    contract.resolver=lambda c:BusinessRequest(c.sha256,'actual_arrival_time','{}',999,'2026-11-03')
    result=asyncio.run(service.chat('门店今天实际收货时刻',context))
    assert '无法确认' in result.content and result.tool_calls_count==0


def test_business_permission_cannot_be_replaced_by_judge_positive(client,session,resources,tmp_path,monkeypatch):
    from app.agent.agent_service import AgentService
    from app.agent.tool_execution import AgentToolContext
    from app.api.agent_dependencies import build_task_registry
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(),'app_environment','test')
    registry,executors=build_task_registry(session)
    contract=IsolatedSemanticContract(pipeline(),business_resolver=lambda c:BusinessRequest(c.sha256,'vehicle_operating_status','{}',1))
    service=AgentService(SimpleNamespace(),registry,executors,checkpoint_path=tmp_path/'denied.sqlite',answer_contract=contract)
    result=asyncio.run(service.chat('车辆状态',AgentToolContext(current_user=resources['driver'])))
    assert result.tool_calls_count==0 and '无法确认' in result.content


from tests.test_agent_knowledge_cache_authorization import graph_context, private_governance as governance  # noqa:E402,F401
from tests.test_ls7_evidence_binding import real_resources as resources  # noqa:E402,F401
