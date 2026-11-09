"""Real LangGraph/tools/business services on owned synthetic SQLite only.

Planner/summary are scripted, not real model quality. Frozen expected labels
are never sent into the Agent. Safe interruption/rejection are NOT task success.
"""
import asyncio
import json
import os
from pathlib import Path

import pytest

from app.agent.model_types import AgentMessageRole, AgentModelMessage
from app.agent.task_workflow import TaskWorkflow
from app.domain.exceptions import BusinessError
from app.models.dispatch_plan import DispatchPlan
from tests.test_agent_task_orchestration import (ScriptedPlanner, service, step, invoke,
                                                 seeded_resources)  # noqa: F401
from tests.test_agent_phase2 import current_admin
from tests.test_agent_dispatch_foundation import DAY

DATASET = json.loads((Path(__file__).parent/'fixtures/ls2_agent_benchmark.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', DATASET, ids=[c['id'] for c in DATASET])
def test_real_agent_benchmark(case, client, session, resources, tmp_path, monkeypatch):
    kind = case['id']
    conv = client.post('/api/v1/agent/conversations').json()['id']
    actor = current_admin(session)
    plans = {
        'ordinary':[step('v','list_vehicles')],
        'multi_tool':[step('orders','list_delivery_demands',{'date':DAY.isoformat()}),step('drivers','list_drivers',{'date':DAY.isoformat()})],
        'dependencies':[
            step('plans','list_dispatch_plans',{'delivery_date':DAY.isoformat()}),
            step('detail','get_dispatch_plan_detail',depends_on=['plans'],bindings={'plan_id':{'step_id':'plans','path':['items',0,'id']}}),
            step('validate','validate_dispatch_plan',depends_on=['detail'],bindings={'plan_id':{'step_id':'detail','path':['plan_id']}})],
        'tool_failure':[step('missing','get_dispatch_plan_detail',{'plan_id':999999})],
        'invalid_parameters':[step('invalid','list_vehicles',{'unexpected':'no'})],
        'interruption':[step('v','list_vehicles')],
        'state_recovery':[step('v','list_vehicles')],
    }
    pending = False
    recovered = False
    if kind in {'dependencies','hitl_confirm','hitl_reject'}:
        response=client.post('/api/v1/auto-dispatch',json={'date':DAY.isoformat()})
        assert response.status_code==200,response.text
        plan_id=response.json()['plan_id']
    if kind.startswith('hitl_'):
        from app.core.config import get_settings
        monkeypatch.setattr(get_settings(),'agent_write_tools_enabled',True)
        model=ScriptedPlanner({'steps':[step('cancel','cancel_dispatch_plan',{'plan_id':plan_id})]},'等待人工确认。')
    elif kind=='multi_turn':
        model=ScriptedPlanner({'clarification':'请确认查询哪辆车？'})
    elif kind=='tool_failure':
        model=ScriptedPlanner({'steps':plans[kind]}, {'steps':[step('plans','list_dispatch_plans',{'delivery_date':DAY.isoformat()})]},'已检查当前列表。')
    elif kind=='interruption':
        class CancelSummary(ScriptedPlanner):
            async def chat(self,messages,tools=None):
                if len(self.messages)==1:
                    row=agent.graph_store.executions(actor.id,conv)[0]
                    agent.graph_store.request_cancellation(row['execution_id'],actor.id,conv)
                    await asyncio.sleep(60)
                return await super().chat(messages,tools)
        model=CancelSummary({'steps':plans[kind]},'不应到达')
    else:
        model=ScriptedPlanner({'steps':plans[kind]},'合成业务查询完成。')
    agent=service(session,tmp_path,model,max_replans=0 if kind=='invalid_parameters' else 1)
    history=(AgentModelMessage(role=AgentMessageRole.USER,content='查询同一天的车辆'),) if kind=='multi_turn' else ()
    if kind=='state_recovery':
        original=TaskWorkflow.analyze
        def broken(self,state):
            raise RuntimeError('synthetic-analysis-fault')
        monkeypatch.setattr(TaskWorkflow,'analyze',broken)
        with pytest.raises(RuntimeError):invoke(agent,session,case['query'],conv)
        record=agent.graph_store.executions(actor.id,conv)[0]
        monkeypatch.setattr(TaskWorkflow,'analyze',original)
        restored=service(session,tmp_path,ScriptedPlanner('已恢复查询结果。'))
        result=asyncio.run(restored.resume_execution(conv,record['execution_id'],actor))
        assert result.status=='COMPLETED' and result.tool_attempts==1
        report=result.model_dump();recovered=True
    elif kind=='interruption':
        with pytest.raises(BusinessError) as error:invoke(agent,session,case['query'],conv)
        assert error.value.code=='AGENT_EXECUTION_CANCELLED'
        report=agent.graph_store.executions(actor.id,conv)[0]
        assert report['status']=='CANCELLED' and report['final_message'] is None
    else:
        result=invoke(agent,session,case['query'],conv,history)
        report=result.execution.model_dump()
        if kind.startswith('hitl_'):
            assert report['status']=='WAITING_APPROVAL'
            assert session.get(DispatchPlan,plan_id).status.value=='DRAFT'
            pending=True
            decision='confirm' if kind=='hitl_confirm' else 'cancel'
            # Re-created service proves persisted checkpoint/HITL resume.
            restored=service(session,tmp_path,ScriptedPlanner())
            asyncio.run(restored.resume_action(conv,result.pending_actions[0].id,actor,decision))
            report=restored.graph_store.executions(actor.id,conv)[0]
            session.expire_all()
            assert session.get(DispatchPlan,plan_id).status.value==('CANCELLED' if decision=='confirm' else 'DRAFT')
        elif kind=='invalid_parameters':assert report['status']=='FAILED' and result.tool_calls_count==0
        elif kind=='multi_turn':
            assert report['status']=='CLARIFICATION'
            assert any(m.content=='查询同一天的车辆' for m in model.messages[0])
        else:
            recovered=kind=='tool_failure' and report['replans']==1
    events=report['events']
    terminal=[e for e in events if e['node']=='tools' and e['status'] in {'SUCCEEDED','FAILED','TIMED_OUT'}]
    actual=dict(id=kind, status=report['status'], intent=report['intent'],
                tools=sorted({e['tool'] for e in events if e.get('tool')}),
                hitl=pending, replans=report['replans'], recovered=recovered,
                tool_attempts=len(terminal),tool_successes=sum(e['status']=='SUCCEEDED' for e in terminal),
                total_ms=report['elapsed_ms'],
                node_ms=[e['elapsed_ms'] for e in events if e['node']!='tools' and e['status'] not in {'RUNNING'}],
                tool_ms=[e['elapsed_ms'] for e in terminal],
                # No args, results, IDs, prompts, or business objects in benchmark.
                events=[{k:e[k] for k in ('node','status','tool','elapsed_ms','error_code')} for e in events])
    target=os.environ.get('LS2_AGENT_OUTPUT')
    if target:
        folder=Path(target).resolve()
        root=Path(__file__).resolve().parents[2]/'docs/evidence'
        assert folder.is_relative_to(root) and folder.is_dir()
        with (folder/(kind+'.json')).open('x',encoding='utf-8') as f:
            json.dump(actual,f,ensure_ascii=False,indent=2)
    # Preserve failed predictions before quality assertions; do not relabel.
    if kind in {'ordinary','multi_tool','dependencies','tool_failure','state_recovery'}:
        assert report['status']=='COMPLETED'
    assert actual['intent']==case['intent']
    assert actual['tools']==sorted(case['tools'])
