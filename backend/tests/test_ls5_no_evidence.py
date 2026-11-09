"""Actual shared Agent model node; scripted adversarial responses, not real LLM."""
import asyncio
from types import SimpleNamespace

import pytest

from app.agent.graph_workflow import AgentWorkflow
from app.agent.model_types import AgentModelResponse,AgentModelMessage,AgentMessageRole,AgentToolCall
from app.agent.tool_execution import AgentToolResult


def scenario(*,hits=(),other=False,pending=False,remaining=0,response=None,revoked=False):
    class Model:
        calls=0
        async def chat(self,*args):
            self.calls+=1
            return response or AgentModelResponse(content='肯定可以，无须任何限制。')
    class Executor:
        def revalidate_cached(self,*args):
            if revoked:raise ValueError('revoked')
    model=Model()
    service=SimpleNamespace(max_tool_calls=2,model_client=model,
        tool_registry=SimpleNamespace(to_openai_tools=lambda:[]),
        executor_registry=SimpleNamespace(get=lambda _:Executor()))
    workflow=AgentWorkflow(service,SimpleNamespace(current_user=SimpleNamespace(id=1),conversation_id=None),None)
    data=AgentToolResult.from_data('search_knowledge_base',dict(results=list(hits),result_count=len(hits),evidence_status='CANDIDATES_UNVERIFIED' if hits else 'NO_EVIDENCE'))
    results={'knowledge':data.model_dump()}
    if other:results['business']=AgentToolResult.from_data('list_vehicles',dict(items=[dict(status='ACTIVE')])).model_dump()
    state=dict(user_id=1,conversation_id=None,messages=[AgentModelMessage(role=AgentMessageRole.SYSTEM,content='synthetic').model_dump()],count=2-remaining,
               read_results=results,pending=[dict(id=1)] if pending else [])
    return workflow,model,state


@pytest.mark.parametrize('content',['肯定可以，无须任何限制。','该门店今天10点已收货。','规则允许车辆超载。'])
def test_empty_knowledge_never_publishes_adversarial_positive_answer(content):
    workflow,model,state=scenario(response=AgentModelResponse(content=content))
    result=asyncio.run(workflow.model(state))
    assert '没有可用的知识证据' in result['content']
    assert content not in result['content'] and result['calls']==[]
    assert model.calls==0  # Bounded synthesis can safely omit a futile call.


def test_nonempty_candidates_are_not_all_refused():
    workflow,model,state=scenario(hits=[dict(chunk_id='a'*64)])
    assert asyncio.run(workflow.model(state))['content']=='肯定可以，无须任何限制。'
    assert model.calls==1  # Does NOT claim this sentence is semantically supported.


@pytest.mark.parametrize('changes',[dict(other=True),dict(pending=True)])
def test_mixed_business_and_hitl_not_replaced_by_empty_rag_refusal(changes):
    workflow,model,state=scenario(**changes)
    assert asyncio.run(workflow.model(state))['content']=='肯定可以，无须任何限制。'
    assert model.calls==1


def test_remaining_tool_budget_can_repair_query():
    response=AgentModelResponse(tool_calls=(AgentToolCall(id='retry-query',name='search_knowledge_base',arguments={'query':'更明确的规则问题'}),))
    workflow,model,state=scenario(remaining=1,response=response)
    assert asyncio.run(workflow.model(state))['calls'][0]['name']=='search_knowledge_base'


def test_final_answer_after_empty_result_cannot_escape_with_remaining_budget():
    workflow,model,state=scenario(remaining=1)
    result=asyncio.run(workflow.model(state))
    assert '没有可用的知识证据' in result['content'] and model.calls==1


def test_revoked_authorization_checked_before_shortcut():
    workflow,model,state=scenario(revoked=True)
    with pytest.raises(ValueError,match='revoked'):asyncio.run(workflow.model(state))
    assert model.calls==0


def test_invalid_empty_model_response_is_not_counted_as_valid_refusal():
    from app.agent.exceptions import AgentModelResponseError
    workflow,model,state=scenario(remaining=1,response=AgentModelResponse(content=None))
    with pytest.raises(AgentModelResponseError):asyncio.run(workflow.model(state))
