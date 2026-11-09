"""Real local Chroma projection; embeddings are explicitly synthetic test vectors."""
from datetime import datetime, timedelta
import pytest
import chromadb
from app.services.agent_memory_service import AgentMemoryService
from app.domain.exceptions import NotFoundError


class TestEmbedding:
    def embed_query(self, text):
        return [1.0, 0.0, 0.0]


@pytest.fixture
def memory(session, tmp_path):
    collection = chromadb.PersistentClient(path=str(tmp_path / 'memory')).get_or_create_collection(
        'agent_user_memory', metadata={'hnsw:space': 'cosine'})
    return AgentMemoryService(session, collection, TestEmbedding())


def test_cross_session_recall_and_user_isolation(memory):
    row = memory.save(1, '优先考虑山区通行能力')
    assert memory.search(1, '车辆') == []
    memory.sync(1)
    other_session = AgentMemoryService(memory.db, memory.collection, TestEmbedding())
    assert other_session.search(1, '车辆')[0]['memory_id'] == row.memory_id
    assert other_session.search(2, '车辆') == []
    with pytest.raises(NotFoundError):
        memory.delete(2, row.memory_id)


def test_scoped_maintenance_preserves_other_users_vectors_and_jobs(memory):
    first = memory.save(1, '甲用户关注冷链')
    second = memory.save(2, '乙用户关注常温')
    assert memory.sync_outbox(user_id=1)['processed'] == 1
    assert memory.stats(1)['outbox_pending'] == 0
    assert memory.stats(2)['outbox_pending'] == 1
    assert memory.sync_outbox(user_id=2)['processed'] == 1

    pending = memory.save(2, '乙用户补充偏好')
    assert memory.rebuild_index(1)['consistent'] is True
    assert memory.collection.count() == 2
    assert memory.search(1, '偏好')[0]['memory_id'] == first.memory_id
    assert memory.search(2, '偏好')[0]['memory_id'] == second.memory_id
    assert memory.stats(1)['chroma_vectors'] == memory.stats(2)['chroma_vectors'] == 1
    assert memory.stats(2)['outbox_pending'] == 1
    assert memory.owned(2, pending.memory_id).status == 'PENDING'


def test_tombstone_hides_stale_vector_and_sync_cleans(memory):
    row = memory.save(1, '优先重型车')
    memory.sync(1)
    memory.delete(1, row.memory_id)
    assert memory.collection.count() == 1
    assert memory.search(1, '车') == []
    memory.sync(1)
    assert memory.collection.count() == 0


def test_update_expiry_and_dedup(memory):
    row = memory.save(1, '优先小型车')
    assert memory.save(1, '优先小型车').memory_id == row.memory_id
    memory.sync(1)
    memory.save(1, '优先重型车', memory_id=row.memory_id)
    assert memory.search(1, '车') == []
    memory.sync(1)
    assert memory.search(1, '车')[0]['content'] == '优先重型车'
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    memory.db.commit()
    assert memory.search(1, '车') == []


def test_failed_embedding_is_retryable(memory):
    row = memory.save(1, '优先山区车')
    class Broken:
        def embed_query(self, text):
            raise TimeoutError()
    memory.embedding = Broken()
    with pytest.raises(TimeoutError):
        memory.sync(1)
    assert row.status == 'PENDING'
    memory.embedding = TestEmbedding()
    memory.sync(1)
    assert row.status == 'ACTIVE'


@pytest.mark.parametrize('text', ['', 'password=secret', '我的密码123', 'x' * 2001])
def test_sensitive_or_invalid_memory_rejected(memory, text):
    with pytest.raises(ValueError):
        memory.save(1, text)


def test_memory_api_ownership_and_confirmation(client, memory, monkeypatch):
    from app.api.v1.endpoints import agent_memory
    monkeypatch.setattr(agent_memory, 'service', lambda db: memory)
    created = client.post('/api/v1/agent/memories', json={'content': '优先山区车', 'confirmed': True})
    assert created.status_code == 200
    mid = created.json()['memory_id']
    assert client.get('/api/v1/agent/memories/' + mid).status_code == 200
    assert client.post('/api/v1/agent/memories', json={'content': '未经确认'}).status_code == 422
    assert client.put('/api/v1/agent/memories/' + mid,
        json={'content': '优先轻型车', 'confirmed': True}).status_code == 200
    foreign = memory.save(999, '其他用户偏好')
    assert client.get('/api/v1/agent/memories/' + foreign.memory_id).status_code == 404
    assert client.delete('/api/v1/agent/memories/' + foreign.memory_id).status_code == 404
    assert client.delete('/api/v1/agent/memories/' + mid).status_code == 200


def test_memory_source_cannot_reference_foreign_conversation(client, memory, monkeypatch):
    from app.api.v1.endpoints import agent_memory
    monkeypatch.setattr(agent_memory, 'service', lambda db: memory)
    response = client.post('/api/v1/agent/memories', json={
        'content': '优先山区车', 'confirmed': True, 'source_conversation_id': 99999})
    assert response.status_code == 404


def test_memory_migration_roundtrip(tmp_path):
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec = importlib.util.spec_from_file_location('memory_migration',
        Path(__file__).parents[1] / 'alembic/versions/20261108_30_agent_memory.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine('sqlite:///' + str(tmp_path / 'migration.sqlite'))
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            assert {'agent_memories', 'agent_memory_versions', 'agent_memory_audits',
                    'agent_memory_outbox', 'agent_session_summaries'} <= set(inspect(connection).get_table_names())
            module.downgrade()
            assert not {'agent_memories', 'agent_memory_versions', 'agent_memory_audits',
                        'agent_memory_outbox', 'agent_session_summaries'} & set(inspect(connection).get_table_names())
