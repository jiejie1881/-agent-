"""长期记忆 API（身份一律取自认证上下文，客户端不得指定 user_id/tenant_id）。"""
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.auth_dependencies import CurrentUser
from app.api.dependencies import DbSession
from app.services.agent_memory_service import memory_service

router = APIRouter(prefix='/agent/memories', tags=['agent-memory'])

MEMORY_TYPES = ('preference', 'habit', 'rule', 'decision', 'project', 'task', 'context', 'profile', 'task_summary')


class MemoryInput(BaseModel):
    # extra='forbid'：客户端若上传 user_id/tenant_id/project_id 直接 422
    model_config = ConfigDict(extra='forbid')

    content: str = Field(min_length=1, max_length=2000)
    memory_type: Literal['preference', 'habit', 'rule', 'decision', 'project', 'task', 'context', 'profile', 'task_summary'] = 'preference'
    memory_key: str | None = Field(default=None, max_length=191)
    importance: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=1.0, ge=0, le=1)
    source_conversation_id: int | None = Field(default=None, gt=0)
    metadata: dict[str, Any] | None = None
    expires_at: datetime | None = None
    confirmed: Literal[True]


class SessionSummaryInput(BaseModel):
    model_config = ConfigDict(extra='forbid')

    session_id: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=2000)
    message_count: int = Field(default=0, ge=0)
    link_memory: bool = True


def service(db):
    from app.core.config import get_settings
    if not get_settings().agent_memory_enabled:
        raise HTTPException(503, '长期记忆未启用')
    return memory_service(db)


def output(row):
    return {
        'memory_id': row.memory_id,
        'memory_type': row.memory_type,
        'memory_key': row.memory_key,
        'content': row.memory_value,
        'importance': row.importance,
        'confidence': row.confidence,
        'version': row.version,
        'status': row.status,
        'source': row.source,
        'source_ref': row.source_ref,
        'source_conversation_id': row.source_conversation_id,
        'created_at': row.created_at,
        'updated_at': row.updated_at,
        'expires_at': row.expires_at,
    }


@router.get('')
def list_memories(current_user: CurrentUser, db: DbSession, limit: int = Query(default=100, ge=1, le=100)):
    return [output(row) for row in service(db).list(current_user.id, limit=limit)]


@router.get('/search')
def search_memories(current_user: CurrentUser, db: DbSession, q: str = Query(min_length=1, max_length=2000),
                    top_k: int = Query(default=5, ge=1, le=10)):
    return service(db).search(current_user.id, q, top_k=top_k)


@router.get('/stats')
def memory_stats(current_user: CurrentUser, db: DbSession):
    return service(db).stats(current_user.id)


@router.post('/sync')
def sync_memories(current_user: CurrentUser, db: DbSession):
    try:
        svc = service(db)
        processed = svc.sync(current_user.id)
        return {'processed': processed, 'outbox': svc.sync_outbox(limit=200, user_id=current_user.id)}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, '向量同步失败，可稍后重试') from None


@router.post('/rebuild-index')
def rebuild_index(current_user: CurrentUser, db: DbSession):
    try:
        return service(db).rebuild_index(current_user.id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, '索引重建失败，可稍后重试') from None


@router.post('/session-summaries')
def write_session_summary(payload: SessionSummaryInput, current_user: CurrentUser, db: DbSession):
    try:
        return service(db).write_session_summary(
            current_user.id,
            session_id=payload.session_id,
            summary=payload.summary,
            message_count=payload.message_count,
            link_memory=payload.link_memory,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


def save(payload, current_user, db, memory_id=None):
    if payload.source_conversation_id:
        from app.models.agent_conversation import AgentConversation
        if db.scalar(select(AgentConversation.id).where(
            AgentConversation.id == payload.source_conversation_id,
            AgentConversation.user_id == current_user.id)) is None:
            raise HTTPException(404, '来源会话不存在')
    fields = payload.model_dump(exclude={'confirmed'})
    try:
        return output(service(db).save(current_user.id, memory_id=memory_id, **fields))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post('')
def create_memory(payload: MemoryInput, current_user: CurrentUser, db: DbSession):
    return save(payload, current_user, db)


@router.get('/{memory_id}')
def get_memory(memory_id: str, current_user: CurrentUser, db: DbSession):
    return output(service(db).owned(current_user.id, memory_id))


@router.get('/{memory_id}/versions')
def memory_versions(memory_id: str, current_user: CurrentUser, db: DbSession,
                    limit: int = Query(default=20, ge=1, le=100)):
    rows = service(db).version_history(current_user.id, memory_id, limit=limit)
    return [
        {
            'version': row.version,
            'content': row.memory_value,
            'status': row.status,
            'source': row.source,
            'created_at': row.created_at,
        }
        for row in rows
    ]


@router.put('/{memory_id}')
def update_memory(memory_id: str, payload: MemoryInput, current_user: CurrentUser, db: DbSession):
    return save(payload, current_user, db, memory_id)


@router.post('/{memory_id}/archive')
def archive_memory(memory_id: str, current_user: CurrentUser, db: DbSession):
    return output(service(db).archive(current_user.id, memory_id))


@router.delete('/{memory_id}')
def delete_memory(memory_id: str, current_user: CurrentUser, db: DbSession, hard: bool = Query(default=False)):
    if hard:
        return service(db).delete(current_user.id, memory_id, hard=True)
    service(db).delete(current_user.id, memory_id)
    return {'status': 'DELETED', 'vector_cleanup': 'PENDING_SYNC'}
