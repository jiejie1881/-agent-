import asyncio
import pytest
from app.rag.reference_policy import decide,meaningful,lexical_eligible,POLICY_VERSION
from tests.test_ls5_no_evidence import scenario


@pytest.fixture(autouse=True)
def explicit_candidate_policy(monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(),'rag_reference_policy',POLICY_VERSION)


@pytest.mark.parametrize('text',['查询门店S101几点收到货？','车辆V205什么时候完成配送？','TASK-09的签收时间是多少？'])
def test_instance_event_needs_authoritative_business_facts(text):
    decision=decide(text,[dict(content='门店启用，车辆出勤。')])
    assert decision.refuse and decision.reason=='INSTANCE_EVENT_REQUIRES_BUSINESS_FACT'


@pytest.mark.parametrize('text',['门店S101的签收时间有什么规定？','车辆V205什么时候必须完成配送？','关于门店签收的操作规则'])
def test_normative_questions_not_classified_as_live_facts(text):
    assert decide(text,[dict(content='门店签收时间规则，司机必须确认。')]).reason!='INSTANCE_EVENT_REQUIRES_BUSINESS_FACT'


def test_function_overlap_does_not_become_evidence():
    assert not meaningful(['会','吗','具体'])
    assert not lexical_eligible('外部会变化吗',['外部','会','变化','吗'],['车辆','会','出勤'])
    assert decide('外部会变化吗',[dict(content='车辆会出勤。')]).refuse


def test_semantic_nonliteral_candidate_remains_unverified_not_globally_dropped():
    result=decide('如何修理发动机',[dict(content='引擎维修说明')])
    assert not result.refuse and result.reason=='CANDIDATES_NOT_SEMANTICALLY_VERIFIED'


def test_modes_are_explicit_and_fail_closed_on_invalid_config():
    assert not decide('门店S901几点收到货',[dict(content='门店规则')],policy='legacy').refuse
    with pytest.raises(ValueError):decide('query',[],policy='unknown')


@pytest.mark.parametrize('query,content',[('下个月月球会下雨吗？','自动派车无法安排的需求会保留在方案的 unassigned_demands 中，并保留未分配原因。'),
                                       ('门店S999今天具体几点收到货？','门店、线路及车型均启用。')])
def test_nonempty_weak_candidates_cannot_bypass_shared_agent_gate(query,content):
    # Shared node used by legacy and TaskWorkflow.finish. No real LLM calls.
    workflow,model,state=scenario(hits=[dict(chunk_id='a'*64,content=content)])
    row=next(iter(state['read_results'].values()))
    row['data']['query']=query
    result=asyncio.run(workflow.model(state))
    assert result['content']!='肯定可以，无须任何限制。' and model.calls==0


def test_same_queries_with_clear_rule_evidence_preserve_answer_path():
    workflow,model,state=scenario(hits=[dict(chunk_id='a'*64,content='每趟不得超过车辆额定载重。')])
    next(iter(state['read_results'].values()))['data']['query']='每趟车辆是否可以超载？'
    asyncio.run(workflow.model(state))
    assert model.calls==1


def test_failure_in_policy_is_not_silently_treated_as_supported(monkeypatch):
    import app.agent.graph_workflow as graph
    workflow,model,state=scenario(hits=[dict(chunk_id='a'*64,content='规则')])
    next(iter(state['read_results'].values()))['data']['query']='规则问题'
    def fail(*args,**kwargs):raise RuntimeError('synthetic gate failure')
    monkeypatch.setattr(graph,'decide',fail)
    with pytest.raises(RuntimeError):asyncio.run(workflow.model(state))
    assert model.calls==0
