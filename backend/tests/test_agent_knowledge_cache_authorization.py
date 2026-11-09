import asyncio
from types import SimpleNamespace

import pytest

from app.agent.agent_service import AgentService
from app.agent.exceptions import AgentToolExecutionError
from app.agent.graph_workflow import AgentWorkflow
from app.agent.knowledge_tools import SearchKnowledgeBaseTool
from app.agent.model_types import AgentModelResponse, AgentToolCall
from app.agent.tool_execution import AgentToolContext, AgentToolExecutorRegistry
from app.agent.tool_registry import AgentToolRegistry
from app.core.config import Settings
from app.rag.governed import GovernedRagFacade
from app.schemas.knowledge import KnowledgeDocumentAclInput
from app.services.knowledge_job_service import KnowledgeJobService
from tests.test_knowledge_management import governance as _governance


@pytest.fixture(name='governance')
def private_governance(session,tmp_path):
    return _governance.__wrapped__(session,tmp_path)


@pytest.fixture
def graph_context(governance,tmp_path,monkeypatch):
    manager,base,actors=governance
    manager.upload(actors['admin'],base.id,'access.md','# 规则\nSYNTHETIC_RESTRICTED_RULE 司机请假需确认代班。'.encode())
    jobs=KnowledgeJobService(manager.session,manager.root,offline=True)
    job=jobs.create(actors['admin'],base.id,'cache-authority-index');jobs.run(actors['admin'],job.id)
    assert job.status=='SUCCEEDED'
    jobs.validate(actors['admin'],job.result_index_id);manager.publish(actors['admin'],job.result_index_id,None,0,True)
    config=Settings(_env_file=None,app_environment='test',rag_governance_enabled=True,rag_governance_offline_enabled=True,
        rag_governance_root=str(manager.root),rag_governance_default_base_id=base.id,rag_retrieval_mode='bm25')
    rag=GovernedRagFacade(manager.session,config)
    calls=[]; original=rag.search_for_actor
    def counted(*a,**kw):
        calls.append(1);return original(*a,**kw)
    monkeypatch.setattr(rag,'search_for_actor',counted)
    tool=SearchKnowledgeBaseTool(rag); registry=AgentToolExecutorRegistry([tool])
    service=AgentService(SimpleNamespace(),AgentToolRegistry(),registry,max_tool_calls=5,checkpoint_path=tmp_path/'graph.sqlite3')
    actor=actors['viewer']; context=AgentToolContext(current_user=actor)
    workflow=AgentWorkflow(service,context,service.graph_store)
    state=dict(user_id=actor.id,conversation_id=None,calls=[],count=0,used=[],pending=[],messages=[],read_results={})
    def execute(state,query='SYNTHETIC_RESTRICTED_RULE'):
        call=AgentToolCall(id='synthetic-'+str(state['count']),name='search_knowledge_base',arguments={'query':query,'knowledge_base_id':base.id})
        state={**state,'calls':[call.model_dump()]}
        return {**state,**asyncio.run(workflow.tools(state))}
    def revoke():
        doc=manager.documents(actors['admin'],base.id)[0]
        manager.update_document_acl(actors['admin'],doc.id,KnowledgeDocumentAclInput(expected_revision=doc.revision,visibility='ADMIN'))
    return SimpleNamespace(manager=manager,base=base,actors=actors,rag=rag,tool=tool,service=service,workflow=workflow,state=state,
        execute=execute,revoke=revoke,calls=calls,context=context)


def test_actual_cache_hit_rechecks_revoked_document_before_return(graph_context):
    g=graph_context;state=g.execute(g.state)
    assert len(g.calls)==1 and 'SYNTHETIC_RESTRICTED_RULE' in str(state['read_results'])
    g.revoke()
    with pytest.raises(AgentToolExecutionError) as denied:
        g.execute(state)
    assert 'SYNTHETIC_RESTRICTED_RULE' not in str(denied.value)


def test_valid_cache_reuse_does_not_repeat_retrieval(graph_context):
    g=graph_context;first=g.execute(g.state);second=g.execute(first)
    assert len(g.calls)==1 and first['read_results']==second['read_results']
    assert second['count']==2


@pytest.mark.parametrize('change',['disabled-user','archived-base','changed-index','expired-proof','cross-user-proof'])
def test_cache_auth_context_changes_fail_closed(graph_context,change):
    g=graph_context;state=g.execute(g.state)
    if change=='disabled-user': g.actors['viewer'].is_active=False;g.manager.session.commit()
    elif change=='archived-base': g.base.status='ARCHIVED';g.manager.session.commit()
    elif change=='changed-index': g.base.active_index_id=None;g.manager.session.commit()
    else:
        data=next(iter(state['read_results'].values()))['data']
        proof=data['knowledge_authorization']
        if change=='expired-proof': proof['authorized_at']=0
        else: proof['user_id']=g.actors['admin'].id
    with pytest.raises(AgentToolExecutionError): g.execute(state)


def test_revocation_while_model_awaits_prevents_final_answer(graph_context):
    g=graph_context;call=AgentToolCall(id='first',name='search_knowledge_base',arguments={'query':'SYNTHETIC_RESTRICTED_RULE','knowledge_base_id':g.base.id})
    class Model:
        def __init__(self): self.count=0
        async def chat(self,messages,tools):
            self.count+=1
            if self.count==1:return AgentModelResponse(tool_calls=(call,))
            g.revoke()
            return AgentModelResponse(content='SYNTHETIC_RESTRICTED_RULE should not escape')
    g.service.model_client=Model()
    with pytest.raises(AgentToolExecutionError):
        asyncio.run(g.service.chat('规则',g.context))


def test_new_request_and_changed_arguments_do_not_share_cached_results(graph_context):
    g=graph_context;first=g.execute(g.state);g.execute(first,query='司机请假')
    assert len(g.calls)==2
    g.execute(g.state)
    assert len(g.calls)==3


@pytest.mark.parametrize('tamper',['missing-proof','forged-content','duplicate-id'])
def test_cached_metadata_cannot_be_forged_or_duplicated(graph_context,tamper):
    g=graph_context;state=g.execute(g.state);data=next(iter(state['read_results'].values()))['data']
    if tamper=='missing-proof': data.pop('knowledge_authorization')
    elif tamper=='forged-content': data['results'][0]['content']='forged secret'
    else: data['results'].append(dict(data['results'][0]))
    with pytest.raises(AgentToolExecutionError): g.execute(state)


def test_authorization_backend_failure_never_uses_old_evidence(graph_context,monkeypatch):
    g=graph_context;state=g.execute(g.state)
    def unavailable(*a,**kw): raise OSError('SYNTHETIC_SECRET_DO_NOT_EXPOSE')
    monkeypatch.setattr(g.rag,'_allowed',unavailable)
    with pytest.raises(AgentToolExecutionError) as error: g.execute(state)
    assert 'SYNTHETIC_SECRET' not in str(error.value)


def test_actual_agent_api_does_not_return_revoked_evidence(graph_context,client,monkeypatch):
    import app.api.agent_dependencies as dependencies
    from app.core.config import get_settings
    g=graph_context
    for name,value in dict(app_environment='test',rag_governance_enabled=True,rag_governance_offline_enabled=True,
            rag_governance_root=str(g.manager.root),rag_governance_default_base_id=g.base.id,rag_retrieval_mode='bm25').items():
        monkeypatch.setattr(get_settings(),name,value)
    class Model:
        def __init__(self): self.count=0
        async def chat(self,messages,tools):
            self.count+=1
            if self.count==1:
                return AgentModelResponse(tool_calls=(AgentToolCall(id='api-cache',name='search_knowledge_base',
                    arguments={'query':'SYNTHETIC_RESTRICTED_RULE','knowledge_base_id':g.base.id}),))
            g.revoke()
            return AgentModelResponse(content='SYNTHETIC_RESTRICTED_RULE cannot be exposed')
    monkeypatch.setattr(dependencies,'LangChainModelClient',Model)
    login=client.post('/api/v1/auth/login',json={'username':'knowledge-viewer','password':'SyntheticPass123!'})
    headers={'Authorization':'Bearer '+login.json()['access_token']}
    conversation=client.post('/api/v1/agent/conversations',json={},headers=headers).json()
    result=client.post(f"/api/v1/agent/conversations/{conversation['id']}/messages",json={'message':'规则'},headers=headers)
    assert result.status_code==403,result.text
    assert 'SYNTHETIC_RESTRICTED_RULE' not in result.text
