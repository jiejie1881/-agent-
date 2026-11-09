from datetime import timedelta

import pytest
from sqlalchemy import select

from app.domain.exceptions import BusinessError, ConflictError
from app.models.audit_log import AuditLog
from app.models.knowledge import KnowledgeBase, KnowledgeChunkRecord, KnowledgeJob, utcnow
from app.rag.evaluation import DeterministicHashEmbedding
from app.services.knowledge_job_service import KnowledgeJobService
from tests.test_knowledge_management import governance as _governance, upload_rule


@pytest.fixture(name="governance")
def private_governance(session, tmp_path):
    return _governance.__wrapped__(session, tmp_path)


def build(governance, key="synthetic-job-1"):
    manager, base, actors = governance
    upload_rule(manager, base, actors["admin"])
    service = KnowledgeJobService(manager.session, manager.root, offline=True)
    job = service.create(actors["admin"], base.id, key)
    service.run(actors["admin"], job.id)
    assert job.status == "SUCCEEDED", (job.stage, job.error_type)
    return service, job


def test_build_validate_publish_are_separate_and_repeat_safe(governance):
    service, job = build(governance)
    manager, base, actors = governance
    assert base.active_index_id is None
    assert service.create(actors["admin"], base.id, job.idempotency_key).id == job.id
    assert service.run(actors["admin"], job.id).attempts == 1
    value = manager.index(actors["admin"], job.result_index_id)
    assert value.status == "CANDIDATE"
    assert not (manager.path(value.manifest_key).parent / "active.json").exists()
    with pytest.raises(ConflictError):
        manager.publish(actors["admin"], value.id, None, 0, True)
    evaluation = service.validate(actors["admin"], value.id)
    assert evaluation.status == "PASS"
    manager.publish(actors["admin"], value.id, None, 0, True)
    assert base.active_index_id == value.id
    with pytest.raises(ConflictError):
        manager.publish(actors["admin"], value.id, None, 0, True)
    assert base.active_index_id == value.id
    assert manager.session.get(KnowledgeBase, base.id).active_index_id == value.id


def test_failed_quality_check_does_not_publish(governance):
    service, job = build(governance)
    manager, base, actors = governance
    assert service.validate(actors["admin"], job.result_index_id, validator=lambda _: False).status == "FAIL"
    with pytest.raises(ConflictError):
        manager.publish(actors["admin"], job.result_index_id, None, 0, True)
    assert base.active_index_id is None


def test_later_failed_validation_cannot_reuse_previous_pass(governance):
    service, job = build(governance)
    manager, base, actors = governance
    assert service.validate(actors["admin"], job.result_index_id).status == "PASS"
    assert service.validate(actors["admin"], job.result_index_id, validator=lambda _: False).status == "FAIL"
    with pytest.raises(ConflictError, match="最近一次"):
        manager.publish(actors["admin"], job.result_index_id, None, 0, True)
    assert base.active_index_id is None


def test_changed_snapshot_conflicts_and_old_validated_index_can_rollback(governance):
    service, first = build(governance)
    manager, base, actors = governance
    service.validate(actors["admin"], first.result_index_id)
    manager.publish(actors["admin"], first.result_index_id, None, base.revision, True)
    doc = manager.documents(actors["admin"], base.id)[0]
    upload_rule(manager, base, actors["admin"], text="# 新规则\n发布前必须再次核对司机出勤。", expected_revision=doc.revision)
    with pytest.raises(ConflictError):
        service.create(actors["admin"], base.id, first.idempotency_key)
    second = service.create(actors["admin"], base.id, "synthetic-job-2")
    service.run(actors["admin"], second.id)
    service.validate(actors["admin"], second.result_index_id)
    manager.publish(actors["admin"], second.result_index_id, first.result_index_id, base.revision, True)
    manager.publish(actors["admin"], first.result_index_id, second.result_index_id, base.revision, True, rollback=True)
    assert base.active_index_id == first.result_index_id
    assert manager.documents(actors["admin"], base.id)[0].current_version_id != first.snapshot["documents"][str(doc.id)]


def test_parse_io_failure_is_bounded_retry_and_preserves_old_index(governance, monkeypatch):
    service, first = build(governance)
    manager, base, actors = governance
    service.validate(actors["admin"], first.result_index_id)
    manager.publish(actors["admin"], first.result_index_id, None, 0, True)
    job = service.create(actors["admin"], base.id, "synthetic-failed-job")
    monkeypatch.setattr(service.management, "read_version", lambda _: (_ for _ in ()).throw(OSError("SYNTHETIC_SECRET_MUST_NOT_PERSIST")))
    assert service.run(actors["admin"], job.id).status == "FAILED"
    assert job.stage == "PARSING" and job.error_type == "OSError" and job.retryable
    service.retry(actors["admin"], job.id)
    service.run(actors["admin"], job.id)
    with pytest.raises(ConflictError):
        service.retry(actors["admin"], job.id)
    assert job.attempts == 2 and base.active_index_id == first.result_index_id
    logs = list(manager.session.scalars(select(AuditLog).where(AuditLog.object_type == "KnowledgeJob")))
    assert "SYNTHETIC_SECRET_MUST_NOT_PERSIST" not in str([a.changes for a in logs])


def test_embedding_failure_is_not_automatically_retried(governance, monkeypatch):
    manager, base, actors = governance
    upload_rule(manager, base, actors["admin"])
    service = KnowledgeJobService(manager.session, manager.root, offline=True)
    job = service.create(actors["admin"], base.id, "embedding-failure")
    monkeypatch.setattr(DeterministicHashEmbedding, "embed_documents", lambda *_: (_ for _ in ()).throw(TimeoutError("synthetic timeout")))
    service.run(actors["admin"], job.id)
    assert job.status == "FAILED" and job.stage == "EMBEDDING" and not job.retryable
    assert job.model_calls == 1
    with pytest.raises(ConflictError):
        service.retry(actors["admin"], job.id)


def test_lease_claim_and_expiry_recovery_do_not_change_active_index(governance):
    manager, base, actors = governance
    upload_rule(manager, base, actors["admin"])
    service = KnowledgeJobService(manager.session, manager.root, offline=True)
    job = service.create(actors["admin"], base.id, "lease-job-test")
    job.status, job.stage, job.attempts, job.lease_token = "RUNNING", "INDEXING", 1, "synthetic-lease"
    job.lease_until, base.running_job_id = utcnow() + timedelta(seconds=30), job.id
    manager.session.commit()
    with pytest.raises(ConflictError):
        service.run(actors["admin"], job.id)
    with pytest.raises(ConflictError):
        service.recover_expired(actors["admin"], job.id)
    job.lease_until = utcnow() - timedelta(seconds=1)
    manager.session.commit()
    service.recover_expired(actors["admin"], job.id)
    assert job.status == "FAILED" and job.error_type == "LEASE_EXPIRED" and job.retryable
    assert base.running_job_id is None and base.active_index_id is None


def test_real_execution_gate_and_manifest_integrity(governance):
    service, job = build(governance)
    manager, base, actors = governance
    blocked = KnowledgeJobService(manager.session, manager.root, offline=False)
    other = blocked.create(actors["admin"], base.id, "blocked-real-job")
    with pytest.raises(BusinessError, match="未授权"):
        blocked.run(actors["admin"], other.id)
    assert other.status == "QUEUED" and other.attempts == 0
    value = manager.index(actors["admin"], job.result_index_id)
    service.validate(actors["admin"], value.id)
    manager.path(value.manifest_key).write_text("{}", encoding="utf-8")
    with pytest.raises(ConflictError):
        manager.publish(actors["admin"], value.id, None, 0, True)
    assert base.active_index_id is None
    assert manager.session.scalar(select(AuditLog).where(AuditLog.action == "RAG_PUBLICATION_FAILED"))
    assert manager.session.scalar(select(KnowledgeJob).where(KnowledgeJob.id == job.id)).status == "SUCCEEDED"


@pytest.mark.parametrize("field", ["content", "document_version_id"])
def test_database_chunk_data_must_match_immutable_manifest(governance, field):
    manager, base, actors = governance
    manager.upload(actors["admin"], base.id, "第二文档.txt", "另一条合成签收规则。".encode())
    service, job = build(governance)
    records = list(manager.session.scalars(select(KnowledgeChunkRecord).where(KnowledgeChunkRecord.index_id == job.result_index_id)))
    first = records[0]
    if field == "content":
        first.content = "合成篡改正文"
    else:
        other = next(r for r in records if r.document_version_id != first.document_version_id)
        first.document_version_id = other.document_version_id
    manager.session.commit()
    with pytest.raises(ConflictError, match="正文或文档版本"):
        service.checked_index(manager.index(actors["admin"], job.result_index_id))


def test_job_deadline_failure_releases_private_claim(governance):
    manager, base, actors = governance
    upload_rule(manager, base, actors["admin"])
    service = KnowledgeJobService(manager.session, manager.root, offline=True, timeout=.000001)
    job = service.create(actors["admin"], base.id, "deadline-private-job")
    service.run(actors["admin"], job.id)
    assert job.status == "FAILED" and job.error_type == "TimeoutError"
    assert base.active_index_id is None and base.running_job_id is None


def test_index_retirement_cannot_remove_active_or_delete_evidence(governance):
    service, first = build(governance)
    manager, base, actors = governance
    service.validate(actors["admin"], first.result_index_id)
    manager.publish(actors["admin"], first.result_index_id, None, 0, True)
    with pytest.raises(ConflictError):
        manager.retire_index(actors["admin"], first.result_index_id, base.revision, True)
    second = service.create(actors["admin"], base.id, "retirement-private-job")
    service.run(actors["admin"], second.id)
    value = manager.index(actors["admin"], second.result_index_id)
    manifest = manager.path(value.manifest_key).read_bytes()
    manager.retire_index(actors["admin"], value.id, base.revision, True)
    assert value.status == "RETIRED" and manager.path(value.manifest_key).read_bytes() == manifest
    assert base.active_index_id == first.result_index_id


def test_replacement_uses_frozen_version_filename_and_txt_parser(governance):
    manager, base, actors = governance
    original = upload_rule(manager, base, actors['admin'])
    document = manager.document(actors['admin'], original.document_id)
    replacement = manager.upload(actors['admin'], base.id, 'replacement.txt', b'# literal heading\nplain text',
                                 document_id=document.id, expected_revision=document.revision)
    service = KnowledgeJobService(manager.session, manager.root, offline=True)
    task = service.create(actors['admin'], base.id, 'changed-file-extension')
    sections = service._sections(task)
    assert len(sections) == 1 and sections[0].content.startswith('# literal heading')
    assert sections[0].source == 'replacement.txt' and sections[0].section == '正文'
    assert sections[0].document_id.endswith(f':version:{replacement.id}')
    assert manager.read_version(original).startswith('# 载重')


def test_expired_lease_cannot_commit_completed_index(governance, monkeypatch):
    from sqlalchemy import update
    from app.models.knowledge import KnowledgeIndexVersion
    from app.rag.versioned_index import VersionedIndex
    manager, base, actors = governance
    upload_rule(manager, base, actors['admin'])
    service = KnowledgeJobService(manager.session, manager.root, offline=True)
    task = service.create(actors['admin'], base.id, 'lease-expires-at-finish')
    original = VersionedIndex.validate_vector

    def expire(chunks, store):
        original(chunks, store)
        manager.session.execute(update(KnowledgeJob).where(KnowledgeJob.id == task.id).values(
            lease_until=utcnow() - timedelta(seconds=1)))
        manager.session.commit()

    monkeypatch.setattr(VersionedIndex, 'validate_vector', staticmethod(expire))
    service.run(actors['admin'], task.id)
    assert task.status == 'FAILED' and task.result_index_id is None
    assert manager.session.scalars(select(KnowledgeIndexVersion)).all() == []
    assert base.active_index_id is None and base.running_job_id is None


def test_start_audit_failure_rolls_back_claim_and_base_lock(governance, monkeypatch):
    manager, base, actors = governance
    upload_rule(manager, base, actors['admin'])
    service = KnowledgeJobService(manager.session, manager.root, offline=True)
    task = service.create(actors['admin'], base.id, 'atomic-start-audit')
    original = service.management.audit

    def reject_start(actor, action, *args):
        if action == 'RAG_JOB_STARTED':
            raise RuntimeError('synthetic audit unavailable')
        return original(actor, action, *args)

    monkeypatch.setattr(service.management, 'audit', reject_start)
    with pytest.raises(RuntimeError, match='audit unavailable'):
        service.run(actors['admin'], task.id)
    manager.session.refresh(task); manager.session.refresh(base)
    assert task.status == 'QUEUED' and task.attempts == 0 and base.running_job_id is None


def test_two_sessions_cannot_execute_same_queued_job_twice(governance):
    import sqlite3
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event
    from sqlalchemy import create_engine, func
    from sqlalchemy.orm import Session
    from app.models.knowledge import KnowledgeIndexVersion

    manager, base, actors = governance
    upload_rule(manager, base, actors['admin'])
    task = KnowledgeJobService(manager.session, manager.root, offline=True).create(
        actors['admin'], base.id, 'two-independent-session-claim')
    actor_type, actor_id, task_id = type(actors['admin']), actors['admin'].id, task.id
    database = manager.root / 'concurrent-claims.sqlite3'
    raw = manager.session.get_bind().raw_connection()
    try:
        with sqlite3.connect(database) as target:
            raw.driver_connection.backup(target)
    finally:
        raw.close()
    engine = create_engine('sqlite+pysqlite:///' + database.as_posix(),
                           connect_args={'check_same_thread': False, 'timeout': 10})
    read_barrier, rejected = Barrier(2), Event()

    def execute():
        with Session(engine, expire_on_commit=False) as session:
            actor = session.get(actor_type, actor_id)
            service = KnowledgeJobService(session, manager.root, offline=True)
            original_get, original_sections = service.get, service._sections

            def simultaneous_read(*args):
                value = original_get(*args)
                assert value.status == 'QUEUED'
                read_barrier.wait(timeout=10)
                return value

            def wait_for_rejection(job):
                assert rejected.wait(timeout=10)
                return original_sections(job)

            service.get, service._sections = simultaneous_read, wait_for_rejection
            try:
                return service.run(actor, task_id).status
            except ConflictError:
                rejected.set()
                return 'CLAIM_REJECTED'

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(execute) for _ in range(2)]
            results = [future.result(timeout=45) for future in futures]
        assert sorted(results) == ['CLAIM_REJECTED', 'SUCCEEDED']
        with Session(engine) as check:
            value = check.get(KnowledgeJob, task_id)
            assert value.attempts == 1 and value.status == 'SUCCEEDED'
            assert check.scalar(select(func.count()).select_from(KnowledgeIndexVersion)) == 1
            assert check.get(type(base), base.id).active_index_id is None
        manager.session.refresh(task)
        assert task.status == 'QUEUED'
    finally:
        engine.dispose()
