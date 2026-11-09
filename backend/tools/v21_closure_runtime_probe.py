"""Run inside the isolated acceptance backend. Embeddings are synthetic."""
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import select, text

from app.domain.enums import UserRole
from app.infrastructure.database.session import SessionLocal
from app.models.user import User
from app.services.agent_memory_index import build_memory_index
from app.services.agent_memory_service import AgentMemoryService
from app.services.auth_service import AuthService


class SyntheticEmbedding:
    def embed_query(self, value):
        return [1.0, 0.0] if '冷链' in value else [0.0, 1.0]


def main():
    phase = os.environ.get('V21_PROBE_PHASE', 'prepare')
    state_path = Path('/app/agent_data/closure-probe.json')
    with SessionLocal() as db:
        identity = db.execute(text('SELECT DATABASE(), @@server_uuid, VERSION()')).one()
        if identity[0] != 'logistics_v21_acceptance':
            raise RuntimeError('Acceptance database identity mismatch')
        migration = db.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
        users = []
        for name in ('v21-closure-a', 'v21-closure-b'):
            row = db.scalar(select(User).where(User.username == name))
            if row is None:
                row = AuthService(db).create_user(name, os.environ['V21_PROBE_PASSWORD'], UserRole.DISPATCHER)
            users.append(row.id)
        collection = build_memory_index(persist_dir='/app/agent_data/memory_chroma',
                                        project_id='v21-closure-probe', embedding_version='synthetic-v1')
        memory = AgentMemoryService(db, collection, SyntheticEmbedding(),
                                    tenant_id='v21-closure-probe', project_id='v21-closure-probe',
                                    embedding_version='synthetic-v1')
        a, b = users
        checks = []
        if phase == 'prepare':
            first = memory.save(a, '合成偏好：岳麓区优先冷链', memory_key='closure-preference')
            second = memory.save(b, '合成偏好：普通常温配送', memory_key='closure-preference')
            memory.sync_outbox(user_id=a)
            assert memory.stats(b)['outbox_pending'] == 1
            memory.sync_outbox(user_id=b)
            assert memory.rebuild_index(a)['consistent']
            assert memory.search(b, '常温')[0]['memory_id'] == second.memory_id
            assert memory.search(b, '冷链') == []
            state_path.write_text(json.dumps([first.memory_id, second.memory_id]), encoding='utf-8')
            checks += ['outbox_user_scope', 'rebuild_user_scope', 'synthetic_similarity']
        elif phase == 'reopen':
            first, second = json.loads(state_path.read_text(encoding='utf-8'))
            assert memory.search(a, '冷链')[0]['memory_id'] == first
            assert memory.search(b, '常温')[0]['memory_id'] == second
            previous_version = memory.owned(a, first).version
            memory.save(a, '合成偏好：更新后的冷链', memory_id=first)
            memory.sync_outbox(user_id=a)
            assert memory.owned(a, first).version == previous_version + 1
            memory.delete(a, first)
            memory.sync_outbox(user_id=a)
            assert memory.search(a, '冷链') == []
            assert memory.stats(a)['chroma_vectors'] == 0
            assert memory.stats(b)['chroma_vectors'] == 1
            checks += ['container_restart_recall', 'update_version', 'delete_projection', 'other_user_retained']
        else:
            raise ValueError('Unsupported acceptance phase')
    route_path = Path('/app/app/api/v1/endpoints/agent_stream.py')
    print(json.dumps({'status': 'PASS', 'phase': phase, 'checks': checks,
                      'database': identity[0], 'database_uuid': identity[1], 'mysql': identity[2],
                      'alembic_revision': migration, 'embedding': 'synthetic',
                      'stream_source_sha256': hashlib.sha256(route_path.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
