"""Browser-only fixture on the acceptance MySQL and volumes. No external model."""
import asyncio
from pathlib import Path
from uuid import uuid4

from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.agent.model_types import AgentModelResponse, AgentToolCall
from app.agent.stream_events import emit
from app.api.agent_dependencies import get_agent_service
from app.api.dependencies import DbSession
from app.core.config import get_settings
from app.main import app


if not get_settings().database_url.endswith('@mysql/logistics_v21_acceptance'):
    raise RuntimeError('Wrong database for synthetic fixture')


class SyntheticModel:
    async def chat(self, messages, tools=None):
        if tools and any(tool['function']['name'] == 'list_vehicles' for tool in tools):
            return AgentModelResponse(tool_calls=(AgentToolCall(
                id=f'closure-synthetic-{uuid4().hex}', name='list_vehicles', arguments={}),))
        pieces = ['合成模型验收：', '已读取隔离车辆列表。', '此回复仅用于验证流式传输。']
        for piece in pieces:
            emit('token', {'text': piece})
            await asyncio.sleep(2.0)
        return AgentModelResponse(content=''.join(pieces))


def synthetic_service(db: DbSession):
    service = get_agent_service(db)
    service.model_client = SyntheticModel()
    return service


app.dependency_overrides[get_agent_service] = synthetic_service
ui = Path('/v21-ui')
app.mount('/assets', StaticFiles(directory=ui / 'assets'), name='closure-assets')


@app.get('/{page:path}', include_in_schema=False)
def frontend(page: str):
    content = (ui / 'index.html').read_text(encoding='utf-8')
    return HTMLResponse(content.replace('<body>', '<body><div style="background:#fff3cd;padding:8px">合成模型，仅用于隔离验收</div>'))
