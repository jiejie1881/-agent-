"""Final closure regressions on owned synthetic SQLite/index resources only."""
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeBase, KnowledgeIndexVersion
from app.services.knowledge_job_service import KnowledgeJobService
from app.services.knowledge_management_service import KnowledgeManagementService
from app.services.knowledge_retrieval_service import KnowledgeRetrievalService
from tests.test_knowledge_lifecycle import build
from tests.test_knowledge_management import governance as _governance
from tests.test_knowledge_api import knowledge_api as _knowledge_api


@pytest.fixture(name="governance")
def private_governance(session, tmp_path):
    return _governance.__wrapped__(session, tmp_path)


@pytest.fixture(name='knowledge_api')
def private_api(client, governance, monkeypatch):
    return _knowledge_api.__wrapped__(client, governance, monkeypatch)


def copy_to_owned_database(governance, *, validated):
    jobs, job = build(governance)
    manager, base, actors = governance
    if validated:
        jobs.validate(actors['admin'], job.result_index_id)
    database = manager.root / 'closure-evaluation-race.sqlite3'
    source = manager.session.get_bind().raw_connection()
    try:
        with sqlite3.connect(database) as target:
            source.driver_connection.backup(target)
    finally:
        source.close()
    engine = create_engine('sqlite+pysqlite:///' + database.as_posix(),
                           connect_args={'timeout': 10, 'check_same_thread': False})
    return engine, manager.root, job.result_index_id, type(actors['admin']), actors['admin'].id, base.id


@pytest.mark.parametrize('action', ['retire_before_pass', 'publish_before_failure'])
def test_smoke_validation_cannot_resurrect_retired_or_demote_published(governance, action):
    engine, root, index_id, actor_type, actor_id, base_id = copy_to_owned_database(
        governance, validated=action == 'publish_before_failure')
    try:
        with Session(engine, expire_on_commit=False) as first:
            actor = first.get(actor_type, actor_id)
            jobs = KnowledgeJobService(first, root, offline=True)

            def interleave(rows):
                assert rows  # real document parsing/BM25 validation already ran
                with Session(engine, expire_on_commit=False) as other:
                    manager = KnowledgeManagementService(other, root, offline=True)
                    base = other.get(KnowledgeBase, base_id)
                    other_actor = other.get(actor_type, actor_id)
                    if action == 'retire_before_pass':
                        manager.retire_index(other_actor, index_id, base.revision, True)
                    else:
                        manager.publish(other_actor, index_id, None, base.revision, True)
                return action == 'retire_before_pass'

            evaluation = jobs.validate(actor, index_id, validator=interleave)
            first.expire_all()
            index = first.get(KnowledgeIndexVersion, index_id)
            base = first.get(KnowledgeBase, base_id)
            if action == 'retire_before_pass':
                assert index.status == 'RETIRED'
                assert evaluation.status == 'BLOCKED'
                assert base.active_index_id is None
            else:
                assert index.status == 'PUBLISHED'
                assert evaluation.status == 'FAIL'
                assert base.active_index_id == index_id
    finally:
        engine.dispose()


def test_fixed_evaluation_error_cannot_demote_concurrently_published_index(governance, monkeypatch):
    engine, root, index_id, actor_type, actor_id, base_id = copy_to_owned_database(governance, validated=True)
    labels = json.loads((Path(__file__).parent/'fixtures/stage3_rag_holdout.json').read_text(encoding='utf8'))
    chunks = [SimpleNamespace(source=src, section=section, chunk_id=f'fixture-{n}-{i}')
              for n,row in enumerate(labels) for i,(src,section) in enumerate(row['expected'])]
    try:
        with Session(engine, expire_on_commit=False) as first:
            actor = first.get(actor_type, actor_id)
            value = first.get(KnowledgeIndexVersion, index_id)
            service = KnowledgeRetrievalService(first, root, offline=True)

            def publish_then_timeout(*args, **kwargs):
                with Session(engine, expire_on_commit=False) as other:
                    manager = KnowledgeManagementService(other, root, offline=True)
                    base = other.get(KnowledgeBase, base_id)
                    manager.publish(other.get(actor_type, actor_id), index_id, None, base.revision, True)
                raise TimeoutError('Synthetic failure after other session published')

            monkeypatch.setattr(service, 'prepare', lambda *a, **kw: (SimpleNamespace(search=publish_then_timeout), value, chunks))
            evaluation = service.evaluate(actor, index_id, 'fixed', 'bm25')
            first.expire_all()
            assert evaluation.status == 'ERROR'
            assert first.get(KnowledgeIndexVersion, index_id).status == 'PUBLISHED'
            assert first.get(KnowledgeBase, base_id).active_index_id == index_id
            assert evaluation.cases[0]['error_type'] == 'TimeoutError'
    finally:
        engine.dispose()


def test_actual_api_version_publish_rollback_delete_never_mixes_chunks(knowledge_api, tmp_path):
    client, manager, base, actors = knowledge_api
    prefix = '/api/v1/knowledge'
    trace = []

    def request(method, path, **kwargs):
        response = client.request(method, prefix + path, **kwargs)
        trace.append({'method': method, 'path': path, 'status': response.status_code,
                      'body': response.json()})
        assert response.status_code == 200, response.text
        return response.json()

    def construct_and_publish(key, *, rollback=None):
        if rollback is None:
            job = request('POST', f'/bases/{base.id}/jobs', json={'idempotency_key': key})
            assert request('POST', f"/jobs/{job['id']}/run")['status'] == 'SUCCEEDED'
            target = request('GET', f"/jobs/{job['id']}")['result_index_id']
            evaluated = request('POST', f'/indexes/{target}/validate', json={'dataset': 'document_smoke'})
            assert evaluated['status'] == 'PASS'
            assert evaluated['metrics']['pipeline']['answer_quality']['status'] == 'NOT RUN'
        else:
            target = rollback
        manager.session.refresh(base)
        request('POST', f"/indexes/{target}/{'rollback' if rollback else 'publish'}", json={
            'expected_active_id': base.active_index_id, 'expected_revision': base.revision, 'confirmed': True})
        return target

    def verify_version(version_id, marker):
        for mode in ('bm25', 'vector', 'hybrid'):
            result = request('POST', '/retrieval/preview', json={'base_id': base.id, 'query': marker, 'strategy': mode})
            assert result['results'] and result['generation'] == 'NOT RUN'
            assert all(hit['document_id'].endswith(f':version:{version_id}') for hit in result['results'])
            assert all(marker in hit['content'] for hit in result['results'])

    try:
        v1 = request('POST', f'/bases/{base.id}/documents', files={
            'file': ('closure.txt', 'CLOSURE_V1_SYNTHETIC：发布前确认车辆出勤。'.encode(), 'text/plain')})
        index1 = construct_and_publish('closure-api-version-one')
        verify_version(v1['id'], 'CLOSURE_V1_SYNTHETIC')
        doc = manager.document(actors['admin'], v1['document_id'])
        v2 = request('POST', f'/bases/{base.id}/documents', files={
            'file': ('closure.txt', 'CLOSURE_V2_SYNTHETIC：司机代班需要人工确认。'.encode(), 'text/plain')},
            data={'document_id': str(doc.id), 'expected_revision': str(doc.revision)})
        # Upload alone intentionally leaves the published snapshot active.
        verify_version(v1['id'], 'CLOSURE_V1_SYNTHETIC')
        index2 = construct_and_publish('closure-api-version-two')
        assert index2 != index1
        verify_version(v2['id'], 'CLOSURE_V2_SYNTHETIC')
        construct_and_publish('unused', rollback=index1)
        verify_version(v1['id'], 'CLOSURE_V1_SYNTHETIC')
        manager.session.refresh(doc)
        request('DELETE', f'/documents/{doc.id}', json={'expected_revision': doc.revision, 'confirmed': True})
        for mode in ('bm25', 'vector', 'hybrid'):
            assert request('POST', '/retrieval/preview', json={
                'base_id': base.id, 'query': 'CLOSURE_V1_SYNTHETIC', 'strategy': mode})['results'] == []
    finally:
        (tmp_path/'API_LIFECYCLE_TRACE.json').write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf8')
