"""Explicit opt-in temporary UI service, using only the reviewed offline runner."""
import asyncio
import json
import re
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.agent.model_types import AgentModelResponse
from app.api.agent_dependencies import get_agent_service
from app.api.dependencies import DbSession
from app.core.config import get_settings
from app.domain.enums import DispatchPlanStatus
from app.main import app
from app.models.dispatch_plan import DispatchPlan
from tests.test_agent_task_orchestration import seeded_resources  # noqa: F401


def test_owned_browser_service(client,session,resources,tmp_path,monkeypatch):
    evidence=Path(__file__).resolve().parents[2]/'docs/evidence/agent-reliability-task3-20261102-db53ad9b'
    if not (evidence/'BROWSER_OPT_IN').exists():pytest.skip('Explicit temporary browser service only')
    dist=evidence/'frontend-release/dist'
    if not (dist/'index.html').exists():raise AssertionError('Current compiled frontend is required')
    monkeypatch.setattr(get_settings(),'agent_write_tools_enabled',True)
    plans=[DispatchPlan(delivery_date=resources['demand'].date,version=v,status=DispatchPlanStatus.DRAFT) for v in [1,2]]
    session.add_all(plans);session.commit()
    run_tag=next(part for part in tmp_path.parts if part.startswith('browser-live'))
    from tests.test_knowledge_management import governance
    from app.services.knowledge_job_service import KnowledgeJobService
    manager,base,actors=governance.__wrapped__(session,tmp_path)
    manager.upload(actors['admin'],base.id,'synthetic.md','# 合成出勤规则\n司机请假后，代班必须经人工确认。'.encode())
    jobs=KnowledgeJobService(session,manager.root,offline=True)
    job=jobs.create(actors['admin'],base.id,'browser-offline-index');jobs.run(actors['admin'],job.id)
    jobs.validate(actors['admin'],job.result_index_id);manager.publish(actors['admin'],job.result_index_id,None,0,True)
    for key,value in {'rag_governance_enabled':True,'rag_governance_offline_enabled':True,
                      'rag_governance_root':str(manager.root),'rag_governance_default_base_id':base.id,
                      'rag_retrieval_mode':'bm25'}.items():monkeypatch.setattr(get_settings(),key,value)
    failures=set()
    class Planner:
        async def chat(self,messages,tools=None):
            query=next((m.content for m in reversed(messages) if m.role.value=='user'),'') or ''
            if 'JSON Schema' in (messages[0].content or ''):
                if '取消方案' in query:
                    ids=re.findall(r'#(\d+)',query);tool='cancel_dispatch_plan';args={'plan_id':int(ids[0]) if ids else plans[0].id}
                    steps=[{'id':'cancel','tool':tool,'arguments':args}]
                elif '知识' in query:
                    steps=[{'id':'knowledge','tool':'search_knowledge_base','arguments':{'query':'司机请假代班人工确认','knowledge_base_id':base.id}}]
                elif '司机' in query:
                    steps=[{'id':'vehicles','tool':'list_vehicles','arguments':{}},
                           {'id':'drivers','tool':'list_drivers','arguments':{'date':'2026-11-10'}}]
                else:steps=[{'id':'vehicles','tool':'list_vehicles','arguments':{}}]
                return AgentModelResponse(content=json.dumps({'steps':steps},ensure_ascii=False))
            if '知识' in query:
                hits=[json.loads(m.content)['data']['results'] for m in messages if m.role.value=='tool' and 'results' in json.loads(m.content).get('data',{})]
                ids=[h['chunk_id'] for rows in hits for h in rows]
                return AgentModelResponse(content='依据合成规则，司机请假后的代班必须人工确认。'+(' [chunk:'+ids[0]+']' if ids else '当前证据不足。'))
            if '慢任务' in query:await asyncio.sleep(30)
            if '恢复' in query and query not in failures:
                failures.add(query);raise ConnectionError('synthetic interruption for browser recovery')
            return AgentModelResponse(content='合成业务查询已完成，结果来自真实业务服务。' if '取消方案' not in query else '取消尚未执行，请核对审批卡片后确认或拒绝。')
    def owned_service(db:DbSession):
        result=get_agent_service(db);result.model_client=Planner();result.execution_deadline_seconds=15
        return result
    app.dependency_overrides[get_agent_service]=owned_service
    app.mount('/assets',StaticFiles(directory=dist/'assets'),name='task3-assets')
    @app.get('/{ui_path:path}',include_in_schema=False)
    def ui(ui_path:str):return FileResponse(dist/'index.html')
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=63423,log_level='warning',access_log=False))
    thread=threading.Thread(target=server.run,name='task3-owned-browser-server')
    thread.start()
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(.05)
        assert server.started
        (evidence/(run_tag+'_READY.json')).write_text(json.dumps({'url':'http://127.0.0.1:63423','database':'isolated synthetic in-memory SQLite via dependency override; NOT MySQL','account':'test-admin','password':'AdminPass123!','plan_ids':[p.id for p in plans],'models':'scripted only','source':'current real FastAPI/Vue','deadline_seconds':15}),encoding='utf8')
        until=time.monotonic()+600
        while time.monotonic()<until and not (evidence/(run_tag+'_FINISH')).exists():time.sleep(.25)
        assert (evidence/(run_tag+'_FINISH')).exists(),'Browser completion not attested within the owned service window'
        from app.models.audit_log import AuditLog
        from app.models.agent_conversation import AgentConversationMessage
        (evidence/(run_tag+'_BUSINESS_FINAL.json')).write_text(json.dumps({'plans':[{'id':p.id,'status':p.status.value} for p in session.scalars(select(DispatchPlan).execution_options(populate_existing=True)).all()],
            'audit_count':len(session.scalars(select(AuditLog)).all()),'conversation_message_count':len(session.scalars(select(AgentConversationMessage)).all())}),encoding='utf8')
    finally:
        server.should_exit=True;thread.join(timeout=15)
        app.dependency_overrides.pop(get_agent_service,None)
    assert not thread.is_alive(),'Owned UI server must be stopped'
