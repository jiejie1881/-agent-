"""长期记忆核心验收（真实 MySQL + 真实 Chroma 持久化目录）。

需要环境变量 ``LOGISTICS_MEMORY_TEST_MYSQL_URL``：指向一个**一次性** MySQL 数据库
（已完成 ``alembic upgrade head``）。未设置时本模块整体 skip，避免污染开发库。

覆盖需求中的 7 类（第 4 类"服务重启恢复"与第 8 类"数据库迁移"由
``scripts/run_memory_acceptance.py`` 以独立进程 + alembic 往返方式执行）。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.agent_memory import (
    AgentMemory,
    AgentMemoryAudit,
    AgentMemoryOutbox,
    AgentMemoryVersion,
    AgentSessionSummary,
)
from app.services.agent_memory_index import build_memory_index
from app.services.agent_memory_service import AgentMemoryService
from app.domain.exceptions import NotFoundError

MYSQL_URL = os.environ.get('LOGISTICS_MEMORY_TEST_MYSQL_URL')

pytestmark = pytest.mark.skipif(not MYSQL_URL, reason='需要真实 MySQL（LOGISTICS_MEMORY_TEST_MYSQL_URL）')

TENANT = 'tenant-log'
PROJECT = 'logistics-dispatch'
EMBEDDING_VERSION = 'test-deterministic-8'

MEMORY_TABLES = ('agent_memory_outbox', 'agent_memory_audits', 'agent_memory_versions',
                 'agent_session_summaries', 'agent_memories')


class DeterministicEmbedding:
    """确定性测试向量（8 维，非语义模型）：仅用于验证索引/同步/隔离链路。"""

    def embed_query(self, text: str) -> list[float]:
        buckets = [0.0] * 8
        for index, char in enumerate(str(text)):
            buckets[index % 8] += (ord(char) % 17) / 17.0
        norm = sum(value * value for value in buckets) ** 0.5 or 1.0
        return [value / norm for value in buckets]


@pytest.fixture(scope='module')
def engine():
    eng = create_engine(MYSQL_URL, pool_pre_ping=True, future=True)
    with eng.begin() as connection:
        existing = {row[0] for row in connection.execute(text('SHOW TABLES'))}
        missing = [name for name in MEMORY_TABLES if name not in existing]
        if missing:
            pytest.fail(f'真实库缺少记忆表 {missing}，请先执行 alembic upgrade head')
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine):
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = factory()
    for table in MEMORY_TABLES:
        session.execute(text(f'DELETE FROM {table}'))
    session.commit()
    try:
        yield session
    finally:
        session.rollback()
        for table in MEMORY_TABLES:
            session.execute(text(f'DELETE FROM {table}'))
        session.commit()
        session.close()


@pytest.fixture()
def store(tmp_path):
    persist_dir = str(tmp_path / 'chroma')
    index = build_memory_index(persist_dir=persist_dir, project_id=PROJECT, embedding_version=EMBEDDING_VERSION)
    try:
        index.reset()
    except Exception:  # noqa: BLE001 - 空集合首次创建时 reset 可能无副作用
        pass
    return index, persist_dir


@pytest.fixture()
def memory(db, store):
    index, _ = store
    return AgentMemoryService(db, index, DeterministicEmbedding(), tenant_id=TENANT,
                              project_id=PROJECT, embedding_version=EMBEDDING_VERSION)


def _drain(service: AgentMemoryService) -> dict:
    return service.sync_outbox(limit=200)


# ---------------------------------------------------------------- 1. MySQL CRUD
def test_write_get_list_update_versions(memory, db):
    row = memory.save(1, '偏好上午装车', memory_type='preference', memory_key='dispatch.time')
    assert row.status == 'PENDING'
    assert row.version == 1

    fetched = memory.owned(1, row.memory_id)
    assert fetched.memory_value == '偏好上午装车'

    rows, total = memory.list_memories(1)
    assert total == 0, '未同步前不是 ACTIVE，不进入默认列表'

    _drain(memory)
    db.refresh(row)
    assert row.status == 'ACTIVE'
    rows, total = memory.list_memories(1)
    assert total == 1 and rows[0].memory_id == row.memory_id

    memory.save(1, '偏好下午装车', memory_type='preference', memory_key='dispatch.time')
    _drain(memory)
    db.expire_all()
    rows, _ = memory.list_memories(1)
    assert len(rows) == 1, '同 user+type+key 必须幂等到同一行'
    assert rows[0].memory_value == '偏好下午装车'
    assert rows[0].version == 2

    history = memory.version_history(1, row.memory_id)
    assert [item.version for item in history] == [2, 1]


def test_audit_does_not_store_plaintext(memory, db):
    row = memory.save(1, '记住车牌 京A12345', memory_type='context')
    audits = db.query(AgentMemoryAudit).filter(AgentMemoryAudit.memory_id == row.memory_id).all()
    assert audits, '必须写入审计'
    serialized = str([(a.before_json, a.after_json) for a in audits])
    assert '京A12345' not in serialized
    assert any((a.after_json or {}).get('value_sha256') for a in audits)


# ---------------------------------------------------------------- 2. Chroma 写入与召回
def test_vector_metadata_and_recall(memory, db):
    row = memory.save(1, '夜间避开城西高架', memory_type='rule', importance=0.9)
    _drain(memory)

    payload = memory.collection.get(where={'memory_id': row.memory_id}, include=['metadatas', 'documents'])
    assert payload['ids'] == [row.memory_id]
    metadata = payload['metadatas'][0]
    assert metadata['tenant_id'] == TENANT
    assert metadata['user_id'] == '1'
    assert metadata['project_id'] == PROJECT
    assert metadata['memory_type'] == 'rule'
    assert metadata['status'] == 'ACTIVE'
    assert metadata['embedding_version'] == EMBEDDING_VERSION

    hits = memory.search(1, '夜间避开城西高架', top_k=3, threshold=0.0)
    assert [hit['memory_id'] for hit in hits] == [row.memory_id]
    assert hits[0]['content'] == '夜间避开城西高架'


def test_embedding_version_isolation_rejected(tmp_path):
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    from app.services.agent_memory_index import (
        MemoryIndexMismatchError,
        build_memory_index,
        collection_name,
    )

    v1 = build_memory_index(persist_dir=str(tmp_path / 'c'), project_id=PROJECT, embedding_version='v1')
    v2 = build_memory_index(persist_dir=str(tmp_path / 'c'), project_id=PROJECT, embedding_version='v2')
    assert v1.collection.name != v2.collection.name, '不同 embedding 版本必须独立集合'
    assert v2.collection.metadata['embedding_version'] == 'v2'

    # 人为把同名集合的版本元数据改成 v0：再用 v1 打开必须被拒绝
    client = chromadb.PersistentClient(path=str(tmp_path / 'x'),
                                       settings=ChromaSettings(anonymized_telemetry=False))
    name = collection_name(PROJECT, 'v1')
    client.get_or_create_collection(
        name=name,
        metadata={'purpose': 'agent_long_term_memory', 'project_id': PROJECT,
                  'embedding_version': 'v0', 'hnsw:space': 'cosine'},
    )
    with pytest.raises(MemoryIndexMismatchError):
        build_memory_index(persist_dir=str(tmp_path / 'x'), project_id=PROJECT, embedding_version='v1')


# ---------------------------------------------------------------- 3. MySQL 与 Chroma 同步
def test_outbox_pending_failed_and_recovered(memory, db):
    row = memory.save(1, '同步失败可重试', memory_type='task')
    assert db.query(AgentMemoryOutbox).filter(AgentMemoryOutbox.status == 'PENDING').count() == 1
    assert memory.collection.count() == 0, '同步前不应有向量'

    class Boom:
        def embed_query(self, text):
            raise TimeoutError('embedding timeout')

    broken = AgentMemoryService(db, memory.collection, Boom(), tenant_id=TENANT,
                                project_id=PROJECT, embedding_version=EMBEDDING_VERSION)
    result = broken.sync_outbox(limit=10)
    assert result['failed'] == 1
    entry = db.query(AgentMemoryOutbox).one()
    assert entry.status == 'FAILED' and entry.attempts == 1
    assert entry.available_at > datetime.utcnow(), '失败必须退避，不能立即无限重试'

    # 退避到期后换回正常 embedding，重试成功
    entry.available_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    result = memory.sync_outbox(limit=10)
    assert result['failed'] == 0 and result['processed'] == 1
    assert memory.stats(1)['consistent'] is True
    assert memory.collection.count() == 1


def test_deleted_row_is_not_projected(memory, db):
    row = memory.save(1, '将被删除', memory_type='task')
    _drain(memory)
    assert memory.collection.count() == 1

    memory.delete(1, row.memory_id)
    _drain(memory)
    assert memory.collection.count() == 0, '墓碑必须清理向量'


# ---------------------------------------------------------------- 5. 用户/租户隔离
def test_user_isolation(memory, db):
    row = memory.save(1, '用户一私有记忆', memory_type='profile')
    _drain(memory)
    with pytest.raises(NotFoundError):
        memory.owned(2, row.memory_id)
    assert memory.search(2, '用户一私有记忆', threshold=0.0) == []
    assert memory.list(2) == []


def test_tenant_and_project_isolation(db, tmp_path):
    index = build_memory_index(persist_dir=str(tmp_path / 'c2'), project_id=PROJECT,
                               embedding_version=EMBEDDING_VERSION)
    other = AgentMemoryService(db, index, DeterministicEmbedding(), tenant_id='tenant-other',
                               project_id=PROJECT, embedding_version=EMBEDDING_VERSION)
    row = memory_write = other.save(1, '其它租户记忆', memory_type='profile')
    other.sync_outbox()
    primary = AgentMemoryService(db, index, DeterministicEmbedding(), tenant_id=TENANT,
                                 project_id=PROJECT, embedding_version=EMBEDDING_VERSION)
    with pytest.raises(NotFoundError):
        primary.owned(1, row.memory_id)
    assert primary.list(1) == []
    assert memory_write.memory_id != ''


# ---------------------------------------------------------------- 6. 删除与索引清理
def test_soft_delete_then_hard_delete(memory, db):
    row = memory.save(1, '临时记忆', memory_type='task')
    _drain(memory)

    result = memory.delete(1, row.memory_id)
    assert result['status'] == 'DELETED'
    _drain(memory)
    db.expire_all()
    kept = db.get(AgentMemory, row.memory_id)
    assert kept.status == 'DELETED' and kept.deleted_at is not None
    assert memory.collection.count() == 0

    purged = memory.delete(1, row.memory_id, hard=True)
    assert purged['status'] == 'PURGED'
    db.expire_all()
    assert db.get(AgentMemory, row.memory_id) is None
    assert db.query(AgentMemoryVersion).filter(AgentMemoryVersion.memory_id == row.memory_id).count() == 0
    assert db.query(AgentMemoryOutbox).filter(AgentMemoryOutbox.memory_id == row.memory_id).count() == 0
    audit_actions = [a.action for a in db.query(AgentMemoryAudit).filter(
        AgentMemoryAudit.memory_id == row.memory_id).all()]
    assert 'HARD_DELETE' in audit_actions


def test_archive_keeps_row_but_drops_vector(memory, db):
    row = memory.save(1, '归档记忆', memory_type='episodic')
    _drain(memory)
    archived = memory.archive(1, row.memory_id)
    assert archived.status == 'ARCHIVED'
    _drain(memory)
    assert memory.collection.count() == 0
    assert memory.search(1, '归档记忆', threshold=0.0) == []


# ---------------------------------------------------------------- 7. 幂等
def test_idempotent_write_and_rebuild(memory, db):
    first = memory.save(1, '幂等信息', memory_type='rule', memory_key='rule.a')
    second = memory.save(1, '幂等信息', memory_type='rule', memory_key='rule.a')
    assert first.memory_id == second.memory_id
    assert db.query(AgentMemory).count() == 1

    _drain(memory)
    _drain(memory)  # 重复排空必须幂等
    assert memory.collection.count() == 1

    rebuild = memory.rebuild_index(1)
    assert rebuild['consistent'] is True
    assert rebuild['chroma_vectors'] == 1
    hits = memory.search(1, '幂等信息', threshold=0.0)
    assert hits and hits[0]['memory_id'] == first.memory_id


def test_session_summary_links_task_memory(memory, db):
    result = memory.write_session_summary(1, session_id='sess-1', summary='今天完成了3条线路排程',
                                          message_count=8)
    assert result['memory_id']
    _drain(memory)
    summary = db.query(AgentSessionSummary).one()
    assert summary.session_id == 'sess-1' and summary.memory_id == result['memory_id']
    hits = memory.search(1, '今天完成了3条线路排程', threshold=0.0)
    assert hits and hits[0]['content'] == '今天完成了3条线路排程'


def test_sensitive_content_rejected(memory):
    for payload in ('api_key=abc123', '司机密码123456', '身份证 110101199001011234', '电话 13800138000'):
        with pytest.raises(ValueError):
            memory.save(1, payload)
