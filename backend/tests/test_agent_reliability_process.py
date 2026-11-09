"""Two separate guarded interpreter lifetimes, one explicitly owned checkpoint."""
import asyncio
import json
import os
from pathlib import Path

import pytest

from app.agent.model_types import AgentMessageRole
from tests.test_agent_task_orchestration import ScriptedPlanner, service, step, invoke, seeded_resources  # noqa: F401
from tests.test_agent_reliability import BrokenSummary
from tests.test_agent_phase2 import current_admin


def test_real_process_restart_recovers_durable_tool_output(client,session,resources):
    phase=os.environ.get('AGENT_RELIABILITY_PROCESS_PHASE')
    if phase not in {'prepare','resume'}:pytest.skip('Requires the reviewed two-process evidence runner')
    folder=Path(os.environ['AGENT_RELIABILITY_PROCESS_ROOT'])
    folder.mkdir(exist_ok=True)
    marker=folder/'prepared.json'
    if phase=='prepare':
        assert not marker.exists(),'Never overwrite the first process evidence'
        agent=service(session,folder,BrokenSummary({'steps':[step('vehicles','list_vehicles')]}))
        with pytest.raises(ConnectionError):invoke(agent,session,'查看车辆',41)
        row=agent.graph_store.executions(current_admin(session).id,41)[0]
        marker.write_text(json.dumps({'pid':os.getpid(),'execution_id':row['execution_id'],
            'vehicle_id':resources['vehicle'].id,'actor_id':current_admin(session).id,'tool_attempts':row['tool_attempts']}),encoding='utf-8')
        assert row['can_resume'] and row['tool_attempts']==1
    else:
        saved=json.loads(marker.read_text(encoding='utf-8'))
        assert saved['pid']!=os.getpid(),'Must run in a different interpreter'
        model=ScriptedPlanner('独立进程已从持久化工具结果恢复。')
        agent=service(session,folder,model)
        result=asyncio.run(agent.resume_execution(41,saved['execution_id'],current_admin(session)))
        assert result.status=='COMPLETED' and result.tool_attempts==1
        assert len(model.messages)==1,'Resume summary, never replan or rerun the successful read'
        tools=[json.loads(m.content)['data'] for m in model.messages[0] if m.role==AgentMessageRole.TOOL]
        assert tools[0]['items'][0]['id']==saved['vehicle_id']
        (folder/'resumed.json').write_text(json.dumps({'pid':os.getpid(),'original_pid':saved['pid'],
            'execution_id':result.execution_id,'status':result.status,'tool_attempts':result.tool_attempts}),encoding='utf-8')
