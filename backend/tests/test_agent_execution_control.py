import asyncio
import sys
from time import monotonic

import pytest

from app.agent.execution_control import (
    Boundary, ExecutionControl, ExecutionDeadlineError, ToolControlContract, run_owned_leaf_process,
)
from app.agent.graph_store import AgentGraphStore
from app.domain.exceptions import NotFoundError
from tests.test_agent_task_orchestration import ScriptedPlanner, service, step, invoke, seeded_resources  # noqa: F401
from tests.test_agent_phase2 import current_admin

PROCESS_CODE_SUCCESS = "print('owned-leaf-ok')"
PROCESS_CODE_BLOCK = "import time; time.sleep(60); print('LATE_RESULT_FORBIDDEN')"


@pytest.mark.parametrize('seconds',[0,-1,float('nan'),float('inf'),True,3601])
def test_invalid_deadlines_are_rejected(seconds):
    with pytest.raises(ValueError):ExecutionControl(seconds)


def test_write_retry_contract_fails_closed():
    with pytest.raises(ValueError):ToolControlContract('write',Boundary.TRANSACTION_RECONCILIATION,1,True,True)


@pytest.mark.parametrize('cause',['deadline','cancel'])
def test_parent_propagates_and_drains_all_parallel_async_children(cause):
    cleaned=[]
    async def scenario():
        flag=[False];control=ExecutionControl(.06,lambda:flag[0])
        async def branch(i):
            try:await asyncio.sleep(60)
            finally:cleaned.append(i)
        async def children():return await asyncio.gather(branch(1),branch(2))
        async def trigger():
            await asyncio.sleep(.015)
            if cause=='cancel':flag[0]=True
        trigger_task=asyncio.create_task(trigger())
        try:
            with pytest.raises(ExecutionDeadlineError if cause=='deadline' else asyncio.CancelledError):
                await control.run(children)
        finally:await trigger_task
        assert not control.children
        assert sorted(cleaned)==[1,2]
        assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
    asyncio.run(scenario())


def test_normal_async_result_and_exception_are_not_rewritten():
    async def scenario():
        async def ok():return {'count':1}
        assert await ExecutionControl(1).run(ok)=={'count':1}
        async def broken():raise ValueError('owned test error')
        with pytest.raises(ValueError):await ExecutionControl(1).run(broken)
    asyncio.run(scenario())


@pytest.mark.parametrize('cause',['deadline','cancel'])
def test_real_owned_blocking_leaf_process_is_killed_and_reaped(cause):
    async def scenario():
        start=monotonic();flag=[False]
        async def signal():
            await asyncio.sleep(.04)
            if cause=='cancel':flag[0]=True
        signal_task=asyncio.create_task(signal())
        try:
            with pytest.raises(ExecutionDeadlineError if cause=='deadline' else asyncio.CancelledError):
                await run_owned_leaf_process((sys._base_executable,'-I','-B','-c',PROCESS_CODE_BLOCK),
                    timeout_seconds=.12 if cause=='deadline' else 10,cancelled=lambda:flag[0])
        finally:await signal_task
        assert monotonic()-start<5,'Reviewed leaf must not wait for its 60-second blocking call'
        assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
    asyncio.run(scenario())


def test_real_owned_process_returns_only_completed_output():
    code,out,err=asyncio.run(run_owned_leaf_process((sys._base_executable,'-I','-B','-c',PROCESS_CODE_SUCCESS),timeout_seconds=5))
    assert code==0 and out.strip()==b'owned-leaf-ok' and not err


def test_cancel_request_is_durable_and_owner_scoped(tmp_path):
    from app.agent.task_plan import ExecutionReport
    store=AgentGraphStore(tmp_path/'graph.sqlite3')
    store.register_execution('one',1,8,'u1:c8:r1')
    store.save_execution(1,ExecutionReport(execution_id='one',conversation_id=8,intent='VEHICLES',status='RUNNING',current_node='tools'))
    with pytest.raises(NotFoundError):store.request_cancellation('one',2,8)
    assert not store.cancellation_requested('one')
    assert store.request_cancellation('one',1,8)
    assert AgentGraphStore(tmp_path/'graph.sqlite3').cancellation_requested('one')


def test_real_workflow_global_deadline_never_publishes_late_summary(client,session,resources,tmp_path):
    class SlowSummary(ScriptedPlanner):
        async def chat(self,messages,tools=None):
            if len(self.messages)==1:await asyncio.sleep(60)
            return await super().chat(messages,tools)
    actor=current_admin(session)
    agent=service(session,tmp_path,SlowSummary({'steps':[step('vehicles','list_vehicles')]},'FORBIDDEN_LATE_SUMMARY'))
    agent.execution_deadline_seconds=.5
    with pytest.raises(ExecutionDeadlineError):invoke(agent,session,'查看车辆',55)
    row=agent.graph_store.executions(actor.id,55)[0]
    assert row['status']=='TIMED_OUT' and row['final_message'] is None and not row['can_resume']
    assert 'FORBIDDEN_LATE_SUMMARY' not in str(row)
    assert agent.graph_store.available(actor.id,55)


def test_confirmed_report_does_not_reuse_pending_approval_text(client,session,tmp_path,monkeypatch):
    from tests.test_agent_reliability import _real_cancel_request
    agent,model,conversation,plan=_real_cancel_request(client,session,tmp_path,monkeypatch)
    pending=invoke(agent,session,'取消方案',conversation)
    asyncio.run(agent.resume_action(conversation,pending.pending_actions[0].id,current_admin(session),'confirm'))
    row=agent.graph_store.executions(current_admin(session).id,conversation)[0]
    assert row['status']=='COMPLETED'
    assert row['final_message']!=pending.content
    assert '已通过人工确认并执行' in row['final_message']


def test_requested_workflow_cancel_has_structured_response_not_internal_error(client,session,resources,tmp_path):
    from app.domain.exceptions import BusinessError
    actor=current_admin(session)
    class CancelSummary(ScriptedPlanner):
        async def chat(self,messages,tools=None):
            if len(self.messages)==1:
                row=agent.graph_store.executions(actor.id,56)[0]
                agent.graph_store.request_cancellation(row['execution_id'],actor.id,56)
                await asyncio.sleep(60)
            return await super().chat(messages,tools)
    agent=service(session,tmp_path,CancelSummary({'steps':[step('v','list_vehicles')]},'late'))
    with pytest.raises(BusinessError) as error:invoke(agent,session,'查看车辆',56)
    assert error.value.code=='AGENT_EXECUTION_CANCELLED' and error.value.status_code==409
    row=agent.graph_store.executions(actor.id,56)[0]
    assert row['status']=='CANCELLED' and row['final_message'] is None and not row['can_resume']
    assert agent.graph_store.available(actor.id,56)


def test_blocking_summary_return_after_deadline_cannot_publish_success(client,session,resources,tmp_path):
    import time
    class BlockingSummary(ScriptedPlanner):
        async def chat(self,messages,tools=None):
            if len(self.messages)==1:time.sleep(.7)
            return await super().chat(messages,tools)
    agent=service(session,tmp_path,BlockingSummary({'steps':[step('v','list_vehicles')]},'LATE_SUCCESS_FORBIDDEN'))
    agent.execution_deadline_seconds=.5
    with pytest.raises(ExecutionDeadlineError):invoke(agent,session,'查看车辆',57)
    row=agent.graph_store.executions(current_admin(session).id,57)[0]
    assert row['status']=='TIMED_OUT' and row['final_message'] is None
    assert 'LATE_SUCCESS_FORBIDDEN' not in str(row)
    assert not any(x['node']=='finish' and x['status']=='COMPLETED' for x in row['events'])
