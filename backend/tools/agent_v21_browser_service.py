"""Temporary UI acceptance server. Synthetic model, isolated SQLite, no egress."""
import asyncio
import os
from pathlib import Path

root = Path(__file__).resolve().parents[2]
out = root / 'docs/evidence/agent-v21-final-20261108-1705'
os.environ.update(DATABASE_URL='sqlite+pysqlite:///' + (out / 'browser.sqlite').as_posix(),
    JWT_SECRET_KEY='v21-local-test-only-key-at-least-32-characters',
    APP_ENVIRONMENT='test', RUN_MIGRATIONS='false', AGENT_MEMORY_ENABLED='false',
    LANGSMITH_TRACING='false', AGENT_CHECKPOINT_PATH=str(out / 'browser-checkpoints.sqlite'))

from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from app.main import app
from app.infrastructure.database.session import engine, SessionLocal
from app.infrastructure.database.base import Base
from app.services.auth_service import AuthService
from app.models.user import User
from app.domain.enums import UserRole
from app.agent.model_types import AgentModelResponse, AgentToolCall
from app.agent.stream_events import emit
from app.api.agent_dependencies import get_agent_service
from sqlalchemy import select

Base.metadata.create_all(engine)
with SessionLocal() as db:
    if db.scalar(select(User).where(User.username == 'v21-acceptance')) is None:
        AuthService(db).create_user('v21-acceptance', 'V21TestOnly123!', UserRole.ADMIN)

class SyntheticModel:
    async def chat(self, messages, tools=None):
        if tools:
            return AgentModelResponse(tool_calls=(AgentToolCall(id='native-browser-call', name='list_vehicles', arguments={}),))
        for text in ['隔离测试：', '当前测试库', '没有车辆记录。']:
            emit('token', {'text': text})
            await asyncio.sleep(0.4)
        return AgentModelResponse(content='隔离测试：当前测试库没有车辆记录。')

def synthetic_agent(db):
    service = get_agent_service(db)
    service.model_client = SyntheticModel()
    return service

from app.api.dependencies import DbSession
def override_agent(db: DbSession):
    return synthetic_agent(db)
app.dependency_overrides[get_agent_service] = override_agent
app.mount('/assets', StaticFiles(directory=root / 'frontend/dist/assets'), name='assets')
@app.get('/{path:path}', response_class=HTMLResponse, include_in_schema=False)
def frontend(path: str):
    html = (root / 'frontend/dist/index.html').read_text(encoding='utf-8')
    return html.replace('<body>', '<body><div style="background:#fff3cd;padding:8px">隔离验收环境：合成模型响应，非真实模型验收</div>')

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=18766)
