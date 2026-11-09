"""Durable LangGraph recovery with real owned business tools, not fake state."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agent.graph_store import AgentGraphStore
from app.agent.task_workflow import TaskWorkflow
from app.agent.task_plan import ExecutionReport
from app.agent.tool_execution import AgentToolContext
from app.domain.exceptions import AgentPendingActionError, NotFoundError
from app.services.agent_conversation_service import AgentConversationService
from tests.test_agent_task_orchestration import ScriptedPlanner, service, step, invoke, seeded_resources  # noqa: F401
from tests.test_agent_phase2 import current_admin


class BrokenSummary(ScriptedPlanner):
    async def chat(self,messages,tools=None):
        if not self.responses:
            raise ConnectionError('synthetic-secret-must-not-log')
        return await super().chat(messages,tools)


def test_summary_failure_restart_uses_checkpoint_without_rerunning_real_tool(client,session,resources,tmp_path):
    conversation=AgentConversationService(session,history_max_messages=20).create(current_admin(session).id)
    agent=service(session,tmp_path,BrokenSummary({'steps':[step('vehicles','list_vehicles')]}))
    with pytest.raises(ConnectionError):invoke(agent,session,'查看车辆',conversation.id)
    saved=agent.graph_store.executions(current_admin(session).id,conversation.id)[0]
    assert saved['status']=='FAILED' and saved['can_resume'] is True
    assert 'synthetic-secret' not in json.dumps(saved)
    resumed=service(session,tmp_path,ScriptedPlanner('已根据原车辆查询结果恢复。'))
    result=asyncio.run(resumed.resume_execution(conversation.id,saved['execution_id'],current_admin(session)))
    assert result.status=='COMPLETED' and result.tool_attempts==1
    assert result.execution_id==saved['execution_id'] and result.revision>saved['revision']
    assert result.final_message=='已根据原车辆查询结果恢复。'
    assert sum(e.node=='tools' and e.status=='SUCCEEDED' for e in result.events)==1
    # Terminal recovery is a readback, not another provider or business call.
    again=asyncio.run(resumed.resume_execution(conversation.id,saved['execution_id'],current_admin(session)))
    assert again==result


def test_middle_node_failure_resumes_next_node_with_real_output(client,session,resources,tmp_path,monkeypatch):
    native=TaskWorkflow.analyze
    def fail(_self,_state):raise RuntimeError('synthetic-node-failure')
    monkeypatch.setattr(TaskWorkflow,'analyze',fail)
    agent=service(session,tmp_path,ScriptedPlanner({'steps':[step('vehicles','list_vehicles')]}))
    with pytest.raises(RuntimeError):invoke(agent,session,'查看车辆',11)
    record=agent.graph_store.executions(current_admin(session).id,11)[0]
    monkeypatch.setattr(TaskWorkflow,'analyze',native)
    restored=service(session,tmp_path,ScriptedPlanner('恢复后的车辆查询。'))
    result=asyncio.run(restored.resume_execution(11,record['execution_id'],current_admin(session)))
    assert result.status=='COMPLETED' and result.tool_attempts==1
    assert any(e.output_fields for e in result.events if e.node=='tools')


def test_checkpoint_owner_and_execution_id_are_server_authoritative(client,session,resources,tmp_path):
    agent=service(session,tmp_path,BrokenSummary({'steps':[step('vehicles','list_vehicles')]}))
    with pytest.raises(ConnectionError):invoke(agent,session,'查看车辆',18)
    row=agent.graph_store.executions(current_admin(session).id,18)[0]
    with pytest.raises(NotFoundError):
        asyncio.run(agent.resume_execution(19,row['execution_id'],current_admin(session)))
    with pytest.raises(NotFoundError):
        asyncio.run(agent.resume_execution(18,'unknown-execution',current_admin(session)))
    assert agent.graph_store.execution(row['execution_id'],current_admin(session).id,18)['status']=='FAILED'


def test_uncertain_write_fails_closed_without_calling_model(client,session,resources,tmp_path):
    agent=service(session,tmp_path,BrokenSummary({'steps':[step('vehicles','list_vehicles')]}))
    with pytest.raises(ConnectionError):invoke(agent,session,'查看车辆',21)
    row=agent.graph_store.executions(current_admin(session).id,21)[0]
    agent.graph_store.uncertain_write(row['execution_id'],True)
    restored=service(session,tmp_path,ScriptedPlanner())
    with pytest.raises(AgentPendingActionError) as failure:
        asyncio.run(restored.resume_execution(21,row['execution_id'],current_admin(session)))
    assert failure.value.code=='AGENT_WRITE_STATE_UNCERTAIN'
    assert restored.model_client.messages==[]


@pytest.mark.parametrize('version',[1,99])
def test_state_version_compatibility_is_explicit(client,session,resources,tmp_path,version):
    agent=service(session,tmp_path,BrokenSummary({'steps':[step('vehicles','list_vehicles')]}))
    with pytest.raises(ConnectionError):invoke(agent,session,'查看车辆',31)
    row=agent.graph_store.executions(current_admin(session).id,31)[0]
    actor=current_admin(session)
    async def update():
        async with AsyncSqliteSaver.from_conn_string(str(agent.graph_store.path)) as saver:
            workflow=TaskWorkflow(agent,AgentToolContext(current_user=actor,conversation_id=31),agent.graph_store)
            graph=workflow.graph(saver)
            config={'configurable':{'thread_id':agent.graph_store.thread(row['execution_id'],actor.id,31)}}
            await graph.aupdate_state(config,{'schema_version':version})
    asyncio.run(update())
    resumed=service(session,tmp_path,ScriptedPlanner('兼容旧状态后恢复。'))
    if version==1:
        assert asyncio.run(resumed.resume_execution(31,row['execution_id'],actor)).status=='COMPLETED'
    else:
        with pytest.raises(AgentPendingActionError) as failure:asyncio.run(resumed.resume_execution(31,row['execution_id'],actor))
        assert failure.value.code=='AGENT_STATE_VERSION'


def test_same_conversation_lock_blocks_duplicate_and_allows_other_threads(tmp_path):
    first=AgentGraphStore(tmp_path/'locks.sqlite3');second=AgentGraphStore(tmp_path/'locks.sqlite3')
    def duplicate():
        with pytest.raises(AgentPendingActionError) as failure:
            with second.lease(1,8):pass
        assert failure.value.code=='AGENT_EXECUTION_BUSY'
        with second.lease(1,9):return True
    with first.lease(1,8):
        with ThreadPoolExecutor(1) as pool:assert pool.submit(duplicate).result(timeout=3)
    with second.lease(1,8):pass


def test_monotonic_revision_and_owner_protected_reports(tmp_path):
    store=AgentGraphStore(tmp_path/'reports.sqlite3')
    report=ExecutionReport(execution_id='one',conversation_id=8,intent='VEHICLES',status='RUNNING',current_node='tools')
    assert store.save_execution(1,report)==1
    assert store.save_execution(1,report)==2
    assert store.execution('one',1,8)['revision']==2
    with pytest.raises(NotFoundError):store.save_execution(2,report)
    assert store.execution('one',1,8)['revision']==2


def test_receipts_are_bound_to_parameters_and_attempt_limit_survives_restart(tmp_path):
    store=AgentGraphStore(tmp_path/'receipts.sqlite3');store.register_execution('x',1,2,'u1:c2:rx')
    assert store.reserve_attempt('x',2)==1
    store.save_receipt('x',0,'v','list_vehicles',{}, {'result':{'tool_name':'list_vehicles','data':{'items':[]}}})
    reopened=AgentGraphStore(tmp_path/'receipts.sqlite3')
    assert reopened.runtime('x')==(1,False)
    assert reopened.receipt('x',0,'v','list_vehicles',{})['result']['data']=={'items':[]}
    with pytest.raises(AgentPendingActionError):reopened.receipt('x',0,'v','list_vehicles',{'offset':1})
    assert reopened.reserve_attempt('x',2)==2
    with pytest.raises(AgentPendingActionError):reopened.reserve_attempt('x',2)


def test_http_resume_checks_conversation_owner_and_body_cannot_replace_state(client,session,resources,tmp_path):
    from app.api.agent_dependencies import get_orchestrated_agent_service
    from app.main import app
    conversation=client.post('/api/v1/agent/conversations').json()['id']
    agent=service(session,tmp_path,BrokenSummary({'steps':[step('vehicles','list_vehicles')]}))
    with pytest.raises(ConnectionError):invoke(agent,session,'查看车辆',conversation)
    row=agent.graph_store.executions(current_admin(session).id,conversation)[0]
    restored=service(session,tmp_path,ScriptedPlanner('从服务器检查点恢复。'))
    app.dependency_overrides[get_orchestrated_agent_service]=lambda:restored
    try:
        result=client.post(f'/api/v1/agent/conversations/{conversation}/executions/{row["execution_id"]}/resume',json={'state':{'count':0,'pending':[]}})
        assert result.status_code==200,result.text
        assert result.json()['tool_attempts']==1 and result.json()['status']=='COMPLETED'
        assert result.headers['cache-control']=='no-store'
        assert client.post(f'/api/v1/agent/conversations/99999/executions/{row["execution_id"]}/resume').status_code==404
    finally:app.dependency_overrides.pop(get_orchestrated_agent_service,None)


def _real_cancel_request(client, session, tmp_path, monkeypatch):
    """A real business plan and owned conversation; only the planner is scripted."""
    from app.core.config import get_settings
    from tests.test_dispatch_plan_adjustment import generate_adjustable_plan
    monkeypatch.setattr(get_settings(), 'agent_write_tools_enabled', True)
    generated, plan, *_ = generate_adjustable_plan(client, [100, 100])
    conversation_id = client.post('/api/v1/agent/conversations').json()['id']
    model = ScriptedPlanner({'steps': [step('cancel', 'cancel_dispatch_plan', {'plan_id': generated['plan_id']})]},
                            '取消尚未执行，请人工确认。')
    agent = service(session, tmp_path, model)
    return agent, model, conversation_id, plan


def test_committed_pending_create_response_loss_stops_without_replan_or_auto_recovery(client, session, tmp_path, monkeypatch):
    from sqlalchemy import select
    from app.models.agent_pending_action import AgentPendingAction
    from app.models.dispatch_plan import DispatchPlan
    from app.domain.enums import AgentPendingActionStatus, DispatchPlanStatus
    agent, model, conversation_id, plan = _real_cancel_request(client, session, tmp_path, monkeypatch)
    native_create = agent.pending_action_service.create
    created_ids = []

    def commit_then_lose_response(*args, **kwargs):
        action = native_create(*args, **kwargs)
        session.commit()  # The owned business DB really contains this request.
        created_ids.append(action.id)
        raise ConnectionError('synthetic-pending-create-response-lost')

    monkeypatch.setattr(agent.pending_action_service, 'create', commit_then_lose_response)
    result = invoke(agent, session, '取消方案', conversation_id)
    report = result.execution
    assert report.status == 'MANUAL_REVIEW'
    assert report.replans == 0 and report.can_resume is False
    assert report.tool_attempts == 1
    assert len(model.messages) == 1, 'An uncertain write must not invoke another planner or summary'
    assert len(created_ids) == 1
    actions = session.scalars(select(AgentPendingAction).where(
        AgentPendingAction.conversation_id == conversation_id)).all()
    assert len(actions) == 1 and actions[0].id == created_ids[0]
    assert actions[0].status == AgentPendingActionStatus.PENDING
    assert session.get(DispatchPlan, plan['id']).status == DispatchPlanStatus.DRAFT
    assert agent.graph_store.runtime(report.execution_id) == (1, True)
    assert 'synthetic-pending-create-response-lost' not in report.model_dump_json()

    restored = service(session, tmp_path, ScriptedPlanner())
    with pytest.raises(AgentPendingActionError) as error:
        asyncio.run(restored.resume_execution(conversation_id, report.execution_id, current_admin(session)))
    assert error.value.code == 'AGENT_WRITE_STATE_UNCERTAIN'
    assert restored.model_client.messages == []
    assert len(session.scalars(select(AgentPendingAction).where(
        AgentPendingAction.conversation_id == conversation_id)).all()) == 1


def test_generic_recovery_reconciles_real_commit_while_checkpoint_still_waits_for_approval(client, session, tmp_path, monkeypatch):
    from sqlalchemy import select
    from app.models.audit_log import AuditLog
    from app.models.dispatch_plan import DispatchPlan
    from app.domain.enums import DispatchPlanStatus
    agent, _model, conversation_id, plan = _real_cancel_request(client, session, tmp_path, monkeypatch)
    pending = invoke(agent, session, '取消方案', conversation_id)
    session.commit()
    action = pending.pending_actions[0]
    actor = current_admin(session)
    execution_id = pending.execution.execution_id

    async def checkpoint():
        async with AsyncSqliteSaver.from_conn_string(str(agent.graph_store.path)) as saver:
            workflow = TaskWorkflow(agent, AgentToolContext(current_user=actor, conversation_id=conversation_id), agent.graph_store)
            thread = agent.graph_store.thread(execution_id, actor.id, conversation_id)
            return await workflow.graph(saver).aget_state({'configurable': {'thread_id': thread}})

    before = asyncio.run(checkpoint())
    assert 'approval' in before.next
    assert before.values['pending'][0]['status'] == 'PENDING'
    asyncio.run(agent.pending_action_service.confirm(conversation_id, action.id, actor))
    stale = asyncio.run(checkpoint())
    assert 'approval' in stale.next and stale.values['pending'][0]['status'] == 'PENDING'
    assert session.get(DispatchPlan, plan['id']).status == DispatchPlanStatus.CANCELLED

    restored = service(session, tmp_path, ScriptedPlanner())
    recovered = asyncio.run(restored.resume_execution(conversation_id, execution_id, actor))
    assert recovered.status == 'COMPLETED' and recovered.execution_id == execution_id
    assert recovered.final_message and recovered.final_message != pending.content
    assert any(event.node == 'recovery' and event.result_summary == {'commit_verified': True, 'replayed': False}
               for event in recovered.events)
    state = asyncio.run(checkpoint())
    assert state.next == ()
    assert state.values['execution']['recovery_verified'] is True
    assert state.values['execution']['original_result_available'] is False
    assert state.values['execution']['action_id'] == action.id
    assert restored.model_client.messages == []
    repeated = asyncio.run(restored.resume_execution(conversation_id, execution_id, actor))
    assert repeated == recovered
    audits = session.scalars(select(AuditLog).where(AuditLog.action == 'DISPATCH_PLAN_CANCELLED')).all()
    assert len(audits) == 1 and audits[0].changes['pending_action_id'] == action.id
    assert restored.model_client.messages == []


@pytest.mark.parametrize('audit_change', ['missing', 'wrong-object'])
def test_generic_recovery_refuses_unverifiable_committed_audit(client, session, tmp_path, monkeypatch, audit_change):
    from sqlalchemy import select
    from app.models.audit_log import AuditLog
    from app.models.dispatch_plan import DispatchPlan
    from app.domain.enums import DispatchPlanStatus
    agent, _model, conversation_id, plan = _real_cancel_request(client, session, tmp_path, monkeypatch)
    pending = invoke(agent, session, '取消方案', conversation_id)
    session.commit()
    actor = current_admin(session)
    action = pending.pending_actions[0]
    asyncio.run(agent.pending_action_service.confirm(conversation_id, action.id, actor))
    audit = session.scalar(select(AuditLog).where(AuditLog.action == 'DISPATCH_PLAN_CANCELLED'))
    assert audit.changes['pending_action_id'] == action.id
    if audit_change == 'missing':
        session.delete(audit)
    else:
        audit.object_id = -1
    session.commit()
    restored = service(session, tmp_path, ScriptedPlanner())
    with pytest.raises(AgentPendingActionError) as error:
        asyncio.run(restored.resume_execution(conversation_id, pending.execution.execution_id, actor))
    assert error.value.code == 'AGENT_ACTION_RECOVERY_UNVERIFIED'
    assert restored.model_client.messages == []
    assert session.get(DispatchPlan, plan['id']).status == DispatchPlanStatus.CANCELLED
    audits = session.scalars(select(AuditLog).where(AuditLog.action == 'DISPATCH_PLAN_CANCELLED')).all()
    assert len(audits) == (0 if audit_change == 'missing' else 1)


@pytest.fixture
def isolated_fresh_read_agent(client, session, resources, tmp_path):
    """Real services on independent connections to an owned SQLite clone."""
    import sqlite3
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.api.agent_dependencies import get_agent_service, get_orchestrated_agent_service

    path = tmp_path / 'reliability-worker-business.sqlite3'
    raw = session.get_bind().raw_connection()
    try:
        with sqlite3.connect(path) as target:
            raw.driver_connection.backup(target)
    finally:
        raw.close()
    engine = create_engine('sqlite+pysqlite:///' + path.as_posix(),
                           connect_args={'check_same_thread': False})
    try:
        with Session(engine, expire_on_commit=False) as primary:
            agent = get_orchestrated_agent_service(primary, get_agent_service(primary))
            agent.graph_store = AgentGraphStore(tmp_path / 'reliability-worker-checkpoints.sqlite3')
            agent.model_client = ScriptedPlanner()
            agent.max_replans = 0
            yield agent, primary
    finally:
        engine.dispose()


def test_workflow_retries_temporary_database_failure_using_fresh_real_service(
        isolated_fresh_read_agent, resources):
    from sqlalchemy.exc import OperationalError
    from app.agent.model_types import AgentMessageRole
    from app.agent.reliability import RetryPolicy

    agent, primary = isolated_fresh_read_agent
    agent.max_tool_calls = 2
    agent.retry_policy = RetryPolicy(max_attempts=2)
    model = ScriptedPlanner({'steps': [step('vehicles', 'list_vehicles')]}, '已完成真实车辆查询。')
    agent.model_client = model
    native = agent.parallel_read
    calls, actual_ids = [], []

    def temporarily_unavailable(name, arguments, context):
        calls.append(name)
        if len(calls) == 1:
            raise OperationalError('synthetic statement must not appear in report', {},
                                   Exception(1213, 'synthetic-sensitive-db-message'))
        result = native(name, arguments, context)
        actual_ids.extend(item['id'] for item in result.data['items'])
        return result

    agent.parallel_read = temporarily_unavailable
    result = invoke(agent, primary, '查看车辆', 71)
    report = result.execution
    assert report.status == 'COMPLETED' and report.tool_attempts == 2
    assert result.tool_calls_count == 2
    assert result.used_tools == ('list_vehicles', 'list_vehicles')
    assert calls == ['list_vehicles', 'list_vehicles']
    assert resources['vehicle'].id in actual_ids
    retry = [event for event in report.events if event.status == 'RETRYING']
    assert len(retry) == 1
    assert retry[0].error_code == 'AGENT_DATABASE_TEMPORARY'
    assert retry[0].error_category == 'DATABASE' and retry[0].attempt == 1
    assert retry[0].retry_delay_ms == 50
    starts = [event for event in report.events if event.node == 'tools' and event.status == 'RUNNING']
    assert [event.attempt for event in starts] == [1, 2]
    assert agent.graph_store.runtime(report.execution_id) == (2, False)
    tool_messages = [message for message in model.messages[-1] if message.role == AgentMessageRole.TOOL]
    assert len(tool_messages) == 1
    assert resources['vehicle'].id in [item['id'] for item in json.loads(tool_messages[0].content)['data']['items']]
    assert 'synthetic-sensitive' not in report.model_dump_json()
    assert 'synthetic statement' not in report.model_dump_json()


def test_parallel_permission_failure_waits_for_real_service_sibling_and_releases_lease(
        isolated_fresh_read_agent, resources):
    from threading import Barrier, Event, Lock, enumerate as live_threads, get_ident
    from time import sleep
    from app.domain.exceptions import PermissionDeniedError
    from tests.test_agent_dispatch_foundation import DAY

    agent, primary = isolated_fresh_read_agent
    model = ScriptedPlanner({'steps': [step('vehicles', 'list_vehicles'),
        step('drivers', 'list_drivers', {'date': DAY.isoformat()})]})
    agent.model_client = model
    native = agent.parallel_read
    barrier = Barrier(2, timeout=5)
    ended = Event()
    lock = Lock()
    tracker = {'active': 0, 'ids': set(), 'driver_ids': []}

    def branch(name, arguments, context):
        with lock:
            tracker['active'] += 1
            tracker['ids'].add(get_ident())
        try:
            barrier.wait()
            if name == 'list_vehicles':
                raise PermissionDeniedError('synthetic-revoked-branch-must-not-be-logged')
            sleep(.03)
            result = native(name, arguments, context)
            tracker['driver_ids'].extend(item['id'] for item in result.data['items'])
            ended.set()
            return result
        finally:
            with lock:
                tracker['active'] -= 1

    agent.parallel_read = branch
    actor = current_admin(primary)
    with pytest.raises(PermissionDeniedError):
        invoke(agent, primary, '查询车辆和司机', 72)
    assert ended.is_set(), 'Permission failure must not return before the sibling completes'
    assert tracker['active'] == 0
    assert resources['driver'].id in tracker['driver_ids']
    assert not any(thread.is_alive() and thread.ident in tracker['ids'] for thread in live_threads())
    assert agent.graph_store.available(actor.id, 72)
    record = agent.graph_store.executions(actor.id, 72)[0]
    assert record['status'] == 'FAILED' and record['tool_attempts'] == 2
    assert any(event['step_id'] == 'drivers' and event['status'] == 'SUCCEEDED' for event in record['events'])
    assert any(event['step_id'] == 'vehicles' and event['error_code'] == 'FORBIDDEN' for event in record['events'])
    assert not any(event['status'] == 'RETRYING' for event in record['events'])
    assert len(model.messages) == 1
    assert 'synthetic-revoked' not in json.dumps(record)


def test_workflow_soft_timeout_discards_real_service_result_after_worker_drains(
        isolated_fresh_read_agent, resources):
    from threading import Event
    from time import sleep

    agent, primary = isolated_fresh_read_agent
    model = ScriptedPlanner({'steps': [step('vehicles', 'list_vehicles')]})
    agent.model_client = model
    agent.tool_timeout_seconds = .001
    native = agent.parallel_read
    ended = Event()
    actual_ids, calls = [], []

    def slow_real_read(name, arguments, context):
        calls.append(name)
        result = native(name, arguments, context)
        actual_ids.extend(item['id'] for item in result.data['items'])
        sleep(.03)
        ended.set()
        return result

    agent.parallel_read = slow_real_read
    result = invoke(agent, primary, '查看车辆', 73)
    report = result.execution
    assert ended.is_set() and resources['vehicle'].id in actual_ids
    assert calls == ['list_vehicles']
    assert report.status == 'FAILED' and report.tool_attempts == 1
    assert report.completed_steps == 0 and report.replans == 0
    assert not any(event.status in {'SUCCEEDED', 'CACHED', 'RETRYING'}
                   for event in report.events if event.node == 'tools')
    timed_out = [event for event in report.events if event.status == 'TIMED_OUT']
    assert len(timed_out) == 1 and timed_out[0].error_code == 'AGENT_TOOL_TIMEOUT'
    assert timed_out[0].error_category == 'TOOL_TIMEOUT'
    assert agent.graph_store.receipt(report.execution_id, 0, 'vehicles', 'list_vehicles', {}) is None
    assert agent.graph_store.available(current_admin(primary).id, 73)
    assert len(model.messages) == 1, 'A timed-out result must not become a successful model observation'


def test_summary_is_running_until_model_finishes_not_prematurely_completed(
        client, session, resources, tmp_path):
    observed = []
    actor = current_admin(session)

    class ObserveSummary(ScriptedPlanner):
        async def chat(self, messages, tools=None):
            if len(self.messages) == 1:
                record = agent.graph_store.executions(actor.id, 74)[0]
                observed.append((record['status'], record.get('final_message')))
                assert record['status'] == 'RUNNING'
                assert record.get('final_message') is None
            return await super().chat(messages, tools)

    model = ObserveSummary({'steps': [step('vehicles', 'list_vehicles')]}, '最终汇总已完成。')
    agent = service(session, tmp_path, model)
    result = invoke(agent, session, '查看车辆', 74)
    assert observed == [('RUNNING', None)]
    assert result.execution.status == 'COMPLETED'
    assert result.execution.final_message == '最终汇总已完成。'


def test_resume_post_uses_agent_read_rbac_instead_of_admin_fallback():
    from fastapi import Request
    from app.api.auth_dependencies import _required_permission
    from app.domain.permissions import Permission

    request = Request({'type': 'http', 'method': 'POST', 'scheme': 'http',
        'path': '/api/v1/agent/conversations/17/executions/server-owned-id/resume',
        'query_string': b'', 'headers': [], 'server': ('testserver', 80)})
    assert _required_permission(request) == Permission.AGENT_READ
