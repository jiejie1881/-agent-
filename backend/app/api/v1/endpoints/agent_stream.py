"""Live SSE attached to the existing conversation/graph. No automatic replay."""
import asyncio
import json
import hashlib
from typing import Annotated
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import APIRouter, HTTPException
from fastapi import Query, Header
from fastapi.responses import StreamingResponse
from app.api.auth_dependencies import CurrentUser
from app.api.agent_dependencies import AgentConversationServiceDependency, AgentServiceDependency
from app.agent.tool_execution import AgentToolContext
from app.agent.stream_events import sink
from app.schemas.agent import AgentChatRequest
from app.agent.stream_store import StreamStore
from app.core.config import get_settings

router = APIRouter(prefix='/agent/conversations', tags=['agent'])
active = {}


@router.post('/{conversation_id}/stream')
async def stream_message(conversation_id: int, data: AgentChatRequest, current_user: CurrentUser,
    conversation_service: AgentConversationServiceDependency, agent_service: AgentServiceDependency,
    operation_id: Annotated[str | None, Header(alias='Idempotency-Key', min_length=8, max_length=128)] = None):
    history = conversation_service.get_model_history(conversation_id, current_user.id)
    key = (current_user.id, conversation_id)
    if key in active:
        raise HTTPException(409, '会话仍在执行，请先确认状态')
    queue = asyncio.Queue(maxsize=512)
    trace_id, message_id = uuid4().hex, uuid4().hex
    sequence = 0
    execution_id = None
    store = StreamStore(get_settings().agent_checkpoint_path)
    operation_id = operation_id or uuid4().hex
    prior = store.claim(current_user.id, conversation_id, operation_id,
        hashlib.sha256(data.message.encode()).hexdigest(), message_id)
    if prior is not None:
        raise HTTPException(409, {'code': 'OPERATION_ALREADY_SUBMITTED', 'message_id': prior[1],
            'message': '该操作已提交，请查询事件或执行记录，不要重复执行'})

    def publish(kind, payload):
        nonlocal sequence, execution_id
        sequence += 1
        execution_id = payload.get('execution_id', execution_id)
        event = {'conversation_id': conversation_id, 'message_id': message_id,
                 'trace_id': trace_id, 'sequence': sequence, 'event_type': kind,
                 'timestamp': datetime.now(timezone.utc).isoformat(), 'payload': payload}
        event['operation_id'] = operation_id
        event['environment'] = get_settings().app_environment
        store.append(current_user.id, event)
        queue.put_nowait(event)  # Backpressure overflow fails the run; never drops tokens.

    async def execute():
        token = sink.set(publish)
        try:
            publish('message_start', {})
            result = await agent_service.chat(data.message, AgentToolContext(
                current_user=current_user, conversation_id=conversation_id, request_id=trace_id), history)
            message = conversation_service.save_exchange(conversation_id, current_user.id, data.message, result.content)
            if result.pending_actions:
                publish('approval_required', {'count': len(result.pending_actions)})
            publish('message_complete', {'message_id': message.id, 'content': result.content,
                'execution': result.execution.model_dump(mode='json') if getattr(result, 'execution', None) else None})
        except asyncio.CancelledError:
            # Workflow records CANCELLED or MANUAL_REVIEW before propagating.
            if not queue.full():
                publish('cancelled', {'cleanup': '查看持久化执行记录确认工具清理状态'})
            raise
        except Exception:
            if not queue.full():
                publish('error', {'code': 'AGENT_RUN_FAILED', 'message': '任务未完成，请查看执行记录后重试'})
        finally:
            sink.reset(token)

    task = asyncio.create_task(execute())
    def cancel():
        try:
            if execution_id:
                agent_service.graph_store.request_cancellation(execution_id, current_user.id, conversation_id)
        finally:
            task.cancel()
    active[key] = (task, cancel)

    async def events():
        try:
            while not task.done() or not queue.empty():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=10)
                except asyncio.TimeoutError:
                    yield ': heartbeat\n\n'
                    continue
                yield f"id: {event['sequence']}\nevent: {event['event_type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            if not task.done():
                cancel()
            await asyncio.gather(task, return_exceptions=True)
            active.pop(key, None)

    return StreamingResponse(events(), media_type='text/event-stream', headers={
        'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no', 'X-Agent-Trace-ID': trace_id})


@router.post('/{conversation_id}/stream/cancel')
async def cancel_stream(conversation_id: int, current_user: CurrentUser,
    conversation_service: AgentConversationServiceDependency):
    conversation_service.get_owned(conversation_id, current_user.id)
    run = active.get((current_user.id, conversation_id))
    if run and not run[0].done():
        run[1]()
    return {'requested': run is not None, 'cleanup_confirmed': False}


@router.get('/{conversation_id}/stream/events')
def read_stream_events(conversation_id: int, message_id: str, current_user: CurrentUser,
    conversation_service: AgentConversationServiceDependency, after: int = 0):
    conversation_service.get_owned(conversation_id, current_user.id)
    return StreamStore(get_settings().agent_checkpoint_path).read(current_user.id, conversation_id, message_id, max(0, after))


@router.get('/{conversation_id}/messages/page')
def message_page(conversation_id: int, current_user: CurrentUser,
    conversation_service: AgentConversationServiceDependency,
    offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=100)):
    from sqlalchemy import select
    from app.models.agent_conversation import AgentConversationMessage
    conversation_service.get_owned(conversation_id, current_user.id)
    rows = conversation_service.session.scalars(select(AgentConversationMessage).where(
        AgentConversationMessage.conversation_id == conversation_id).order_by(
        AgentConversationMessage.id).offset(offset).limit(limit)).all()
    return [{'id': row.id, 'role': row.role, 'content': row.content, 'created_at': row.created_at} for row in rows]


@router.get('/{conversation_id}/stream/metrics')
def stream_metrics(conversation_id: int, current_user: CurrentUser,
    conversation_service: AgentConversationServiceDependency):
    conversation_service.get_owned(conversation_id, current_user.id)
    return StreamStore(get_settings().agent_checkpoint_path).statistics(current_user.id, conversation_id)
