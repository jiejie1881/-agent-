"""Dedicated disposable MySQL + actual Chroma consistency/migration acceptance."""
import importlib.util
import json
from pathlib import Path
import time
import chromadb
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.services.agent_memory_service import AgentMemoryService

root = Path(__file__).resolve().parents[2]
out = root / 'docs/evidence/agent-v21-final-20261108-1705'
engine = create_engine('mysql+pymysql://root:V21IsolatedDatabaseOnly@127.0.0.1:18767/agent_v21_test',
                       connect_args={'connect_timeout': 2, 'read_timeout': 5, 'write_timeout': 5})
result = {'status': 'BLOCKED', 'environment': 'disposable_mysql_container', 'embedding': 'synthetic_unit_vector', 'checks': []}
try:
    for attempt in range(60):
        try:
            with engine.connect() as db:
                identity = db.execute(text('SELECT DATABASE(),@@server_uuid,@@version')).one()
            break
        except Exception:
            if attempt == 59:
                raise
            time.sleep(1)
    assert identity[0] == 'agent_v21_test' and identity[2].startswith('8.4.')
    result['identity'] = {'database': identity[0], 'server_uuid': identity[1], 'version': identity[2]}
    spec = importlib.util.spec_from_file_location('memory_migration', root / 'backend/alembic/versions/20261108_30_agent_memory.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as db:
        assert inspect(db).get_table_names() == []
        with Operations.context(MigrationContext.configure(db)):
            migration.upgrade()
        assert len(inspect(db).get_table_names()) == 5
    result['checks'].append('migration_upgrade')
    class Embedding:
        def embed_query(self, text):
            return [1.0, 0.0, 0.0]
    collection = chromadb.PersistentClient(path=str(out / 'mysql-chroma')).get_or_create_collection(
        'v21_mysql_memory', metadata={'hnsw:space': 'cosine'})
    with Session(engine, expire_on_commit=False) as db:
        memory = AgentMemoryService(db, collection, Embedding(), embedding_version='acceptance-v1')
        row = memory.save(1, '山区配送优先考虑通行能力')
        memory.sync(1)
        assert memory.search(1, '配送')[0]['memory_id'] == row.memory_id
        assert memory.search(2, '配送') == []
        result['checks'].extend(['mysql_chroma_write_recall', 'user_isolation'])
        memory.save(1, '优先考虑载重', memory_id=row.memory_id)
        assert memory.search(1, '配送') == []
        memory.sync(1)
        assert memory.search(1, '配送')[0]['content'] == '优先考虑载重'
        result['checks'].append('version_invalidation_and_sync')
    with Session(engine) as reopened:
        memory = AgentMemoryService(reopened, collection, Embedding(), embedding_version='acceptance-v1')
        assert memory.search(1, '配送')[0]['memory_id'] == row.memory_id
        result['checks'].append('session_reopen_recall')
        memory.delete(1, row.memory_id)
        assert memory.search(1, '配送') == []
        memory.sync(1)
        assert collection.count() == 0
        result['checks'].append('tombstone_and_vector_cleanup')
    with engine.begin() as db:
        with Operations.context(MigrationContext.configure(db)):
            migration.downgrade()
        assert inspect(db).get_table_names() == []
    result['checks'].append('migration_downgrade')
    result['status'] = 'PASS'
except Exception as exc:
    result['error_type'] = type(exc).__name__
finally:
    engine.dispose()
    (out / 'mysql-acceptance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(result['status'])
