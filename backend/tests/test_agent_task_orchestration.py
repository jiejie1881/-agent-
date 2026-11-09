"""Real services/SQL/dispatch on owned synthetic SQLite; only the LLM is scripted."""
import asyncio
import json
import sqlite3
from threading import Barrier, get_ident

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.agent.agent_service import AgentService
from app.agent.model_types import AgentModelResponse, AgentModelMessage, AgentMessageRole
from app.agent.task_plan import Intent, route_intent
from app.agent.tool_execution import AgentToolContext
from app.api.agent_dependencies import build_task_registry, get_agent_service, get_orchestrated_agent_service
from app.domain.exceptions import PermissionDeniedError
from app.models.dispatch_plan import DispatchPlan
from app.services.agent_pending_action_service import AgentPendingActionService
from tests.test_agent_dispatch_foundation import resources as _resources, DAY
from tests.test_agent_phase2 import current_admin


@pytest.fixture(name='resources')
def seeded_resources(session):
    return _resources.__wrapped__(session)


class ScriptedPlanner:
    def __init__(self,*responses):self.responses=list(responses);self.messages=[];self.tool_schemas=[]
    async def chat(self,messages,tools=None):
        self.messages.append(messages)
        self.tool_schemas.append(tools)
        value=self.responses.pop(0)
        return AgentModelResponse(content=json.dumps(value,ensure_ascii=False) if isinstance(value,dict) else value)


def step(id,tool,arguments=None,**kwargs):
    return dict(id=id,tool=tool,arguments=arguments or {},**kwargs)


def service(session,tmp_path,model,**kwargs):
    registry,executors=build_task_registry(session)
    return AgentService(model,registry,executors,orchestration=True,
        pending_action_service=AgentPendingActionService(session,executors,15),
        checkpoint_path=tmp_path/'tasks.sqlite3',**kwargs)


def invoke(agent,session,query='分析调度运力',conversation=None,history=()):
    return asyncio.run(agent.chat(query,AgentToolContext(current_user=current_admin(session),conversation_id=conversation),history))


@pytest.mark.parametrize('query,intent',[
    ('查看车辆',Intent.VEHICLES),('查看司机',Intent.DRIVERS),('查询订单',Intent.DEMANDS),
    ('查看运输任务',Intent.TRANSPORT),('查询出勤',Intent.ATTENDANCE),('分析运力',Intent.CAPACITY),
    ('生成方案',Intent.DISPATCH),('查询异常',Intent.EXCEPTIONS),('物流知识',Intent.KNOWLEDGE),
    ('查询司机及订单',Intent.COMPOSITE),('取消方案',Intent.WRITE),
])
def test_intent_routes_have_explicit_tool_catalogue(query,intent):
    actual,_,allowed=route_intent(query)
    assert actual==intent and allowed
    if intent!=Intent.WRITE:assert 'cancel_dispatch_plan' not in allowed


def test_single_real_vehicle_tool_and_observation_redaction(client,session,resources,tmp_path):
    model=ScriptedPlanner({'steps':[step('vehicles','list_vehicles')]},'车辆查询完成。')
    agent=service(session,tmp_path,model)
    result=invoke(agent,session,'查看车辆')
    bound_names = {tool['function']['name'] for tool in model.tool_schemas[0]}
    assert 'list_vehicles' in bound_names
    assert 'cancel_dispatch_plan' not in bound_names
    assert result.execution.status=='COMPLETED' and result.tool_calls_count==1
    data=[json.loads(m.content)['data'] for m in model.messages[-1] if m.role==AgentMessageRole.TOOL]
    assert data[0]['items'][0]['id']==resources['vehicle'].id
    assert 'password_hash' not in result.execution.model_dump_json()
    assert resources['driver'].password_hash not in result.execution.model_dump_json()


def test_native_call_ids_survive_planning_and_observation(client, session, resources, tmp_path):
    from app.agent.model_types import AgentToolCall
    class NativeModel:
        async def chat(self, messages, tools=None):
            if tools:
                assert any(t['function']['name'] == 'list_vehicles' for t in tools)
                return AgentModelResponse(tool_calls=(AgentToolCall(
                    id='call_PROVIDER-Original-ID', name='list_vehicles', arguments={}),))
            observations = [m for m in messages if m.role == AgentMessageRole.TOOL]
            assert observations[-1].tool_call_id == 'call_PROVIDER-Original-ID'
            assert json.loads(observations[-1].content)['data']['items'][0]['id'] == resources['vehicle'].id
            return AgentModelResponse(content='已查询车辆。')
    result = invoke(service(session, tmp_path, NativeModel()), session, '查看车辆')
    assert result.execution.status == 'COMPLETED'


def test_three_step_dependencies_bind_real_plan_ids_and_validate(client,session,resources,tmp_path):
    created=client.post('/api/v1/auto-dispatch',json={'date':DAY.isoformat()})
    assert created.status_code==200,created.text
    plan_id=created.json()['plan_id']
    model=ScriptedPlanner({'steps':[
        step('plans','list_dispatch_plans',{'delivery_date':DAY.isoformat()}),
        step('detail','get_dispatch_plan_detail',depends_on=['plans'],bindings={'plan_id':{'step_id':'plans','path':['items',0,'id']}}),
        step('check','validate_dispatch_plan',depends_on=['detail'],bindings={'plan_id':{'step_id':'detail','path':['plan_id']}}),
    ]},'已查询并校验现有方案，没有发布。')
    result=invoke(service(session,tmp_path,model),session,'检查调度方案详情和约束')
    assert result.execution.status=='COMPLETED' and result.tool_calls_count==3
    data=[json.loads(m.content)['data'] for m in model.messages[-1] if m.role==AgentMessageRole.TOOL]
    assert data[1]['plan_id']==data[2]['plan_id']==plan_id
    assert session.get(DispatchPlan,plan_id).status.value=='DRAFT'


def test_real_capacity_and_candidate_do_not_persist_business_state(client,session,resources,tmp_path):
    before=session.scalar(select(func.count()).select_from(DispatchPlan))
    model=ScriptedPlanner({'steps':[
        step('demand','list_delivery_demands',{'date':DAY.isoformat()}),
        step('drivers','list_drivers',{'date':DAY.isoformat()}),
        step('capacity','analyze_capacity',{'date':DAY.isoformat()},depends_on=['demand','drivers']),
        step('candidate','preview_dispatch_candidate',{'date':DAY.isoformat()},depends_on=['capacity']),
    ]},'候选仅供人工参考，未保存或发布。')
    result=invoke(service(session,tmp_path,model),session,'查询订单和司机，分析运力并生成调度候选')
    assert result.execution.status=='COMPLETED' and result.tool_calls_count==4
    data=[json.loads(m.content)['data'] for m in model.messages[-1] if m.role==AgentMessageRole.TOOL]
    candidate=data[-1]
    assert candidate['validation']['is_valid'],candidate
    assert candidate['candidate']['trips'][0]['demand_ids']==[resources['demand'].id]
    assert candidate['persisted'] is False and candidate['published'] is False
    assert session.scalar(select(func.count()).select_from(DispatchPlan))==before
    session.refresh(resources['demand']);assert resources['demand'].status.value=='PENDING'


def test_parallel_reads_use_distinct_real_sessions(client,session,resources,tmp_path):
    path=tmp_path/'parallel.sqlite3'
    raw=session.get_bind().raw_connection()
    try:
        with sqlite3.connect(path) as target:raw.driver_connection.backup(target)
    finally:raw.close()
    engine=create_engine('sqlite+pysqlite:///'+path.as_posix(),connect_args={'check_same_thread':False})
    barrier=Barrier(2,timeout=10);threads=set()
    try:
        with Session(engine,expire_on_commit=False) as primary:
            agent=get_orchestrated_agent_service(primary,get_agent_service(primary))
            model=ScriptedPlanner({'steps':[step('demand','list_delivery_demands',{'date':DAY.isoformat()}),
                step('drivers','list_drivers',{'date':DAY.isoformat()})]},'并行查询完成。')
            agent.model_client=model;agent.graph_store=type(agent.graph_store)(tmp_path/'parallel-graph.sqlite3')
            native=agent.parallel_read
            def overlap(name,args,context):
                threads.add(get_ident());barrier.wait();return native(name,args,context)
            agent.parallel_read=overlap
            result=invoke(agent,primary,'查询订单和司机')
            assert result.execution.status=='COMPLETED'
            groups={e.parallel_group for e in result.execution.events if e.node=='tools'}
            assert len(threads)==2 and len(groups)==1 and None not in groups
            data=[json.loads(m.content)['data'] for m in model.messages[-1] if m.role==AgentMessageRole.TOOL]
            assert any(d.get('items',[{}])[0].get('id')==resources['demand'].id for d in data)
    finally:engine.dispose()


def test_empty_branch_skips_dependent_detail_without_inventing_id(client,session,resources,tmp_path):
    model=ScriptedPlanner({'steps':[
        step('plans','list_dispatch_plans',{'delivery_date':DAY.isoformat()}),
        step('detail','get_dispatch_plan_detail',depends_on=['plans'],
             bindings={'plan_id':{'step_id':'plans','path':['items',0,'id']}},
             when={'source':{'step_id':'plans','path':['items']},'operator':'nonempty'}),
    ]},'当天暂无方案。')
    result=invoke(service(session,tmp_path,model),session,'查看运输任务')
    assert result.tool_calls_count==1
    assert any(e.step_id=='detail' and e.status=='SKIPPED' for e in result.execution.events)


def test_tool_failure_replans_once_using_real_fallback(client,session,resources,tmp_path):
    model=ScriptedPlanner({'steps':[step('missing','get_dispatch_plan_detail',{'plan_id':999999})]},
        {'steps':[step('plans','list_dispatch_plans',{'delivery_date':DAY.isoformat()})]},'没有找到指定方案，已检查当天列表。')
    result=invoke(service(session,tmp_path,model),session,'查看调度方案详情')
    assert result.execution.replans==1 and result.execution.status=='COMPLETED'
    assert result.tool_calls_count==2 and any(e.status=='FAILED' for e in result.execution.events)


def test_invalid_plans_and_step_limit_are_bounded(client,session,resources,tmp_path):
    model=ScriptedPlanner({'steps':[step('one','list_vehicles'),step('two','list_vehicles')]})
    result=invoke(service(session,tmp_path,model,max_tool_calls=1,max_replans=0),session,'查看车辆')
    assert result.execution.status=='FAILED' and result.tool_calls_count==0 and len(model.messages)==1


def test_invalid_structured_output_stops_without_executing_tools(client,session,resources,tmp_path):
    model=ScriptedPlanner('not JSON; token=must-not-log')
    result=invoke(service(session,tmp_path,model,max_replans=0),session,'查看车辆')
    assert result.execution.status=='FAILED' and result.tool_calls_count==0
    assert 'must-not-log' not in result.execution.model_dump_json()


def test_owned_history_reaches_planner(client,session,resources,tmp_path):
    model=ScriptedPlanner({'clarification':'请确认是否仍查询同一天？'},)
    result=invoke(service(session,tmp_path,model),session,'那另一个呢',history=(
        AgentModelMessage(role=AgentMessageRole.USER,content='查询2026-11-10的车辆'),))
    assert result.execution.status=='CLARIFICATION'
    assert any(m.content=='查询2026-11-10的车辆' for m in model.messages[0])


def test_driver_cannot_use_management_orchestration(client,session,resources,tmp_path):
    model=ScriptedPlanner({'steps':[step('one','list_vehicles')]})
    agent=service(session,tmp_path,model)
    with pytest.raises(PermissionDeniedError):
        asyncio.run(agent.chat('查看车辆',AgentToolContext(current_user=resources['driver'])))
    assert model.messages==[]


def test_write_pause_confirm_restart_preserves_existing_hitl(client,session,resources,tmp_path,monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(),'agent_write_tools_enabled',True)
    created=client.post('/api/v1/auto-dispatch',json={'date':DAY.isoformat()}).json()
    conv=client.post('/api/v1/agent/conversations').json()['id']
    model=ScriptedPlanner({'steps':[step('cancel','cancel_dispatch_plan',{'plan_id':created['plan_id']})]},'取消尚未执行，请人工确认。')
    agent=service(session,tmp_path,model)
    result=invoke(agent,session,'取消方案',conversation=conv)
    assert result.execution.status=='WAITING_APPROVAL' and result.tool_calls_count==1
    assert session.get(DispatchPlan,created['plan_id']).status.value=='DRAFT'
    action=result.pending_actions[0]
    resumed=service(session,tmp_path,ScriptedPlanner())
    asyncio.run(resumed.resume_action(conv,action.id,current_admin(session),'confirm'))
    session.expire_all();assert session.get(DispatchPlan,created['plan_id']).status.value=='CANCELLED'
    assert resumed.graph_store.executions(current_admin(session).id,conv)[0]['status']=='COMPLETED'


def test_execution_api_does_not_disclose_other_users_reports(client,session,resources,tmp_path):
    from app.main import app
    conv=client.post('/api/v1/agent/conversations').json()['id']
    agent=service(session,tmp_path,ScriptedPlanner({'steps':[step('one','list_vehicles')]},'完成'))
    invoke(agent,session,'查看车辆',conversation=conv)
    app.dependency_overrides[get_agent_service]=lambda:agent
    try:
        response=client.get(f'/api/v1/agent/conversations/{conv}/executions')
        assert response.status_code==200 and response.json()[0]['completed_steps']==1
        assert 'password_hash' not in response.text
        assert client.get(f'/api/v1/agent/conversations/{conv+100}/executions').status_code==404
        from app.services.auth_service import AuthService
        from app.domain.enums import UserRole
        AuthService(session).create_user('task-other','SyntheticOther123!',UserRole.VIEWER)
        token=client.post('/api/v1/auth/login',json={'username':'task-other','password':'SyntheticOther123!'}).json()['access_token']
        assert client.get(f'/api/v1/agent/conversations/{conv}/executions',
                          headers={'Authorization':f'Bearer {token}'}).status_code==404
    finally:app.dependency_overrides.pop(get_agent_service,None)


def test_exception_business_tools_and_authorized_rag_share_one_plan(client,session,resources,tmp_path,monkeypatch):
    from app.core.config import Settings
    from app.rag.governed import GovernedRagFacade
    from app.services.knowledge_job_service import KnowledgeJobService
    from tests.test_knowledge_management import governance
    import app.api.agent_dependencies as dependencies
    manager,base,actors=governance.__wrapped__(session,tmp_path)
    manager.upload(actors['admin'],base.id,'synthetic_exception.md','# 异常建议\n配送异常先核实状态，未经人工确认不得修改或结案。'.encode())
    jobs=KnowledgeJobService(session,manager.root,offline=True)
    job=jobs.create(actors['admin'],base.id,'task-exception-index');jobs.run(actors['admin'],job.id)
    assert job.status=='SUCCEEDED'
    jobs.validate(actors['admin'],job.result_index_id)
    manager.publish(actors['admin'],job.result_index_id,None,base.revision,True)
    settings=Settings(_env_file=None,app_environment='test',rag_governance_enabled=True,
        rag_governance_offline_enabled=True,rag_governance_root=str(manager.root),rag_governance_default_base_id=base.id,
        rag_retrieval_mode='bm25')
    monkeypatch.setattr(dependencies,'build_rag_service',lambda **kwargs:GovernedRagFacade(session,settings))
    from app.services.exception_case_service import ExceptionCaseService
    case=ExceptionCaseService(session).create('UNASSIGNED_DEMAND',resources['demand'].id,None,current_admin(session))
    model=ScriptedPlanner({'steps':[
        step('exceptions','get_daily_exceptions',{'date':DAY.isoformat()}),
        step('cases','list_exception_cases',depends_on=['exceptions']),
        step('demands','list_delivery_demands',depends_on=['cases'],bindings={
            'date':{'step_id':'cases','path':['items',0,'date']},'store_id':{'step_id':'cases','path':['items',0,'store_id']}}),
        step('tasks','list_transport_tasks',{'date':DAY.isoformat()},depends_on=['demands']),
        step('rules','search_knowledge_base',{'query':'配送异常人工确认','knowledge_base_id':base.id},depends_on=['tasks']),
    ]},'已核查异常和运输任务，并检索处理规则；未修改业务状态。')
    result=invoke(service(session,tmp_path,model),session,'查询异常工单、关联运输任务并检索处理知识')
    assert result.execution.status=='COMPLETED' and result.tool_calls_count==5
    returned=[json.loads(m.content)['data'] for m in model.messages[-1] if m.role==AgentMessageRole.TOOL]
    assert returned[1]['items'][0]['id']==case.id
    assert returned[2]['items'][0]['id']==resources['demand'].id
    assert returned[-1]['knowledge_authorization']['base_id']==base.id
    assert '未经人工确认' in returned[-1]['results'][0]['content']


def test_default_http_entry_runs_planned_business_workflow_and_persists_history(client,session,resources,tmp_path,monkeypatch):
    import app.api.agent_dependencies as dependencies
    from app.core.config import get_settings
    model=ScriptedPlanner({'steps':[step('drivers','list_drivers',{'date':DAY.isoformat()}),
        step('capacity','analyze_capacity',{'date':DAY.isoformat()},depends_on=['drivers'])]},'已分析真实合成司机及运力。')
    monkeypatch.setattr(dependencies,'LangChainModelClient',lambda:model)
    monkeypatch.setattr(get_settings(),'agent_checkpoint_path',str(tmp_path/'http-graph.sqlite3'))
    conv=client.post('/api/v1/agent/conversations').json()['id']
    response=client.post(f'/api/v1/agent/conversations/{conv}/messages',json={'message':'分析司机和运力'})
    assert response.status_code==200,response.text
    data=response.json();assert data['execution']['status']=='COMPLETED' and data['tool_calls_count']==2
    detail=client.get(f'/api/v1/agent/conversations/{conv}').json()
    assert len(detail['messages'])==2 and detail['messages'][-1]['content']==data['message']['content']
    reports=client.get(f'/api/v1/agent/conversations/{conv}/executions').json()
    assert reports[0]['execution_id']==data['execution']['execution_id']


@pytest.mark.parametrize('kind',['cycle','unknown-tool','unrouted-write','unknown-dependency','duplicate-step'])
def test_plan_validation_rejects_dependency_and_capability_violations(client,session,resources,tmp_path,kind,monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(),'agent_write_tools_enabled',True)
    a=step('one','list_vehicles'); b=step('two','list_vehicles')
    if kind=='cycle':a['depends_on']=['two'];b['depends_on']=['one']
    elif kind=='unknown-tool':a['tool']='delete_all_data'
    elif kind=='unrouted-write':a=step('one','cancel_dispatch_plan',{'plan_id':1})
    elif kind=='unknown-dependency':a['depends_on']=['missing']
    else:b['id']='one'
    result=invoke(service(session,tmp_path,ScriptedPlanner({'steps':[a,b]}),max_replans=0),session,'查看车辆')
    assert result.execution.status=='FAILED' and result.tool_calls_count==0


def test_planner_and_summary_use_distinct_stable_ids_in_same_budget(client,session,resources,tmp_path):
    import httpx
    import time
    from app.agent.langchain_client import LangChainModelClient
    from app.core.model_budget import ModelBudget,BudgetPolicy,budget_context
    from tests.test_model_budget import settings
    calls=[]
    def handler(request):
        calls.append(request)
        content=json.dumps({'steps':[step('one','list_vehicles')]}) if len(calls)==1 else '已查询车辆'
        return httpx.Response(200,json={'id':'synthetic','model':'test-model','choices':[
            {'message':{'role':'assistant','content':content},'finish_reason':'stop'}]})
    folder=tmp_path/'phase-billing';folder.mkdir()
    budget=ModelBudget(folder/ModelBudget.FILENAME,BudgetPolicy(3,30,10,max_input_bytes=50000,max_output_tokens=2048))
    budget.initialize_new(expires_at=time.time()+60)
    model=LangChainModelClient(settings(),transport=httpx.MockTransport(handler))
    with budget_context(budget):
        result=invoke(service(session,tmp_path,model),session,'查看车辆')
    assert result.execution.status=='COMPLETED' and len(calls)==2
    with sqlite3.connect(budget.path) as db:
        rows=db.execute('select operation_id,reserved,status from calls').fetchall()
    assert len(rows)==2 and sum(r[1] for r in rows)==20
    assert {r[0].split(':')[-1] for r in rows}=={'planner-0','summary'}
    assert all(r[2]=='HTTP_SUCCEEDED' for r in rows)


def test_model_timeout_records_failure_and_keeps_conversation_atomic(client,session,resources,tmp_path,monkeypatch):
    import app.api.agent_dependencies as dependencies
    from app.agent.exceptions import AgentModelTimeoutError
    from app.core.config import get_settings
    class Timeout:
        async def chat(self,*args):raise AgentModelTimeoutError()
    monkeypatch.setattr(dependencies,'LangChainModelClient',Timeout)
    monkeypatch.setattr(get_settings(),'agent_checkpoint_path',str(tmp_path/'timeout-graph.sqlite3'))
    conv=client.post('/api/v1/agent/conversations').json()['id']
    response=client.post(f'/api/v1/agent/conversations/{conv}/messages',json={'message':'查询司机'})
    assert response.status_code==504
    assert client.get(f'/api/v1/agent/conversations/{conv}').json()['messages']==[]
    reports=client.get(f'/api/v1/agent/conversations/{conv}/executions').json()
    assert reports[0]['status']=='FAILED' and reports[0]['tool_attempts']==0


def test_invalid_candidate_validation_forces_replan_instead_of_success(client,session,resources,tmp_path):
    from app.agent.task_workflow import TaskWorkflow
    agent=service(session,tmp_path,ScriptedPlanner())
    flow=TaskWorkflow(agent,AgentToolContext(current_user=current_admin(session)),agent.graph_store)
    state=dict(intent='DISPATCH',count=1,replans=0,pending=[],
        plan={'steps':[step('candidate','preview_dispatch_candidate',{'date':DAY.isoformat()})]},
        step_status={'candidate':'SUCCEEDED'},outputs={'candidate':{'validation':{'is_valid':False}}})
    analyzed=flow.analyze(state)
    assert analyzed['failed'] and analyzed['plan_error']=='CANDIDATE_VALIDATION_FAILED'
    assert flow.decide(analyzed)['next']=='replan'


def test_transport_projection_returns_real_order_and_draft_status(client,session,resources,tmp_path):
    generated=client.post('/api/v1/auto-dispatch',json={'date':DAY.isoformat()}).json()
    model=ScriptedPlanner({'steps':[step('tasks','list_transport_tasks',{'date':DAY.isoformat()})]},'已列出草稿运输任务。')
    result=invoke(service(session,tmp_path,model),session,'查看运输任务')
    data=next(json.loads(m.content)['data'] for m in model.messages[-1] if m.role==AgentMessageRole.TOOL)
    assert result.execution.status=='COMPLETED'
    assert data['items'][0]['plan_id']==generated['plan_id'] and data['items'][0]['plan_status']=='DRAFT'
    assert data['items'][0]['demand_ids']==[resources['demand'].id]


def test_replanning_rechecks_acl_after_model_before_consuming_old_evidence(client,session,resources,tmp_path,monkeypatch):
    from app.core.config import Settings
    from app.rag.governed import GovernedRagFacade
    from app.schemas.knowledge import KnowledgeDocumentAclInput
    from app.services.knowledge_job_service import KnowledgeJobService
    from tests.test_knowledge_management import governance
    import app.api.agent_dependencies as dependencies
    manager,base,actors=governance.__wrapped__(session,tmp_path)
    version=manager.upload(actors['admin'],base.id,'rule.md','# 规则\n司机请假必须经过人工确认。'.encode())
    jobs=KnowledgeJobService(session,manager.root,offline=True)
    job=jobs.create(actors['admin'],base.id,'replan-authorization-index');jobs.run(actors['admin'],job.id)
    jobs.validate(actors['admin'],job.result_index_id);manager.publish(actors['admin'],job.result_index_id,None,base.revision,True)
    config=Settings(_env_file=None,app_environment='test',rag_governance_enabled=True,rag_governance_offline_enabled=True,
        rag_governance_root=str(manager.root),rag_governance_default_base_id=base.id,rag_retrieval_mode='bm25')
    monkeypatch.setattr(dependencies,'build_rag_service',lambda **kwargs:GovernedRagFacade(session,config))
    class RevokeDuringReplan(ScriptedPlanner):
        async def chat(self,messages,tools=None):
            if len(self.messages)==1:
                doc=manager.document(actors['admin'],version.document_id)
                manager.update_document_acl(actors['admin'],doc.id,
                    KnowledgeDocumentAclInput(expected_revision=doc.revision,visibility='ADMIN'))
            return await super().chat(messages,tools)
    model=RevokeDuringReplan({'steps':[
        step('rules','search_knowledge_base',{'query':'司机请假人工确认','knowledge_base_id':base.id}),
        step('missing','get_dispatch_plan_detail',{'plan_id':99999},depends_on=['rules'])]},
        {'steps':[step('vehicles','list_vehicles')]})
    agent=service(session,tmp_path,model)
    from app.agent.exceptions import AgentToolExecutionError
    with pytest.raises(AgentToolExecutionError) as error:
        asyncio.run(agent.chat('查询规则和调度方案详情，失败时检查车辆',AgentToolContext(current_user=actors['viewer'])))
    assert error.value.status_code==403
    assert len(model.messages)==2  # No summary or additional tool after revocation.


def test_unsupported_publish_cannot_be_substituted_with_cancel(client,session,resources,tmp_path,monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(),'agent_write_tools_enabled',True)
    generated=client.post('/api/v1/auto-dispatch',json={'date':DAY.isoformat()}).json()
    model=ScriptedPlanner({'steps':[step('cancel','cancel_dispatch_plan',{'plan_id':generated['plan_id']})]})
    result=invoke(service(session,tmp_path,model,max_replans=0),session,'发布方案')
    assert result.execution.status=='FAILED' and result.pending_actions==() and result.tool_calls_count==0
    assert session.get(DispatchPlan,generated['plan_id']).status.value=='DRAFT'
