import sqlite3

import pytest

from tools.run_knowledge_jobs import main
from app.services.knowledge_job_service import KnowledgeJobService
from tests.test_knowledge_management import governance as _governance, upload_rule


@pytest.fixture(name="governance")
def private_governance(session, tmp_path):
    return _governance.__wrapped__(session, tmp_path)


def test_one_shot_worker_uses_only_explicit_private_file_database(governance, capsys):
    manager, base, actors = governance
    upload_rule(manager, base, actors["admin"])
    job = KnowledgeJobService(manager.session, manager.root, offline=True).create(actors["admin"], base.id, "worker-private-job")
    engine = manager.session.get_bind()
    assert engine.url.database == ":memory:"
    database = manager.root / "knowledge-offline.sqlite3"
    manager.session.commit()
    raw = engine.raw_connection()
    try:
        with sqlite3.connect(database) as target:
            raw.driver_connection.backup(target)
    finally:
        raw.close()
    assert main(["--storage-root", str(manager.root), "--database", str(database),
                 "--actor", str(actors["admin"].id), "--job", str(job.id), "--offline"]) == 0
    assert '"status": "SUCCEEDED"' in capsys.readouterr().out
    # Independent recovered target changes never update the memory source.
    manager.session.refresh(job)
    assert job.status == "QUEUED"


def test_worker_rejects_missing_or_non_whitelisted_database_before_connect(governance):
    manager, _, actors = governance
    with pytest.raises(SystemExit) as exc:
        main(["--storage-root", str(manager.root), "--database", str(manager.root / "unapproved.sqlite3"),
              "--actor", str(actors["admin"].id), "--job", "1", "--offline"])
    assert exc.value.code == 2
