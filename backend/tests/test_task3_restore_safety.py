"""Offline synthetic restore and startup checks; never use live backup sources."""
import io
from contextlib import closing
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import sys
import tarfile
import threading
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from candidate_backup_validation import archive_entries, restore_archive
from candidate_backup_validation import sqlite_fingerprint


def pack(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, content in files:
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    return stream.getvalue()


@pytest.mark.parametrize("name", [
    "NUL", "CON.txt", "PRN", "AUX", "COM1.db", "LPT9.png",
    "folder/NUL.json", ".. /escape.txt", "folder./proof.png",
    "folder /proof.png", "proof.png.", "proof.png ", "proof?.png",
    "proof|.png", "control\nname.png", "COM¹.txt", "LPT².db",
])
def test_nonportable_archive_names_rejected_before_any_restore_write(tmp_path, name):
    payload = pack([(name, b"synthetic-only")])
    # Require pure in-memory preflight rejection before attempting filesystem I/O.
    with pytest.raises(ValueError):
        archive_entries(payload)
    with pytest.raises(ValueError):
        restore_archive(payload, tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("names", [
    ["proof.png", "PROOF.PNG"],
    ["Proof/photo.png", "proof/PHOTO.png"],
    ["folder", "folder/proof.png"],
    ["folder/proof.png", "folder"],
])
def test_alias_and_file_directory_conflicts_rejected_before_restore(tmp_path, names):
    payload = pack([(name, b"synthetic-only") for name in names])
    with pytest.raises(ValueError):
        archive_entries(payload)
    with pytest.raises(ValueError):
        restore_archive(payload, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_portable_unicode_names_remain_supported(tmp_path):
    result = restore_archive(pack([("中文目录/回单.png", b"synthetic-only")]), tmp_path)
    assert result["restore"] == "PASS" and result["temporary_copy_removed"]
    assert "中文目录/回单.png" in result["entries"]
    assert list(tmp_path.iterdir()) == []


def test_synthetic_business_backup_reopen_preserves_proof_and_audit(client, session, tmp_path):
    from app.core.config import get_settings
    from tests.test_same_day_plan_replacement import setup_case

    data = setup_case(client, session)
    session.commit()
    snapshot = tmp_path / "synthetic-business.sqlite3"
    raw = session.get_bind().raw_connection()
    try:
        source = raw.driver_connection
        expected = sqlite_fingerprint(source)
        with closing(sqlite3.connect(snapshot)) as destination:
            source.backup(destination)
    finally:
        raw.close()
    snapshot_bytes = snapshot.read_bytes()
    snapshot_sha = hashlib.sha256(snapshot_bytes).hexdigest()
    upload_root = Path(get_settings().upload_root)
    with closing(sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True)) as db:
        proof_paths = [r[0] for r in db.execute("SELECT file_path FROM delivery_proofs")]
    assert len(proof_paths) == 1
    files = {"business.sqlite3": snapshot_bytes}
    for name in proof_paths:
        files["uploads/" + name] = (upload_root / name).read_bytes()
    payload = pack(list(files.items()))
    archive_path = tmp_path / "synthetic-bundle.tar"
    archive_path.write_bytes(payload)
    validation = restore_archive(payload, tmp_path)
    assert validation["entries"]["business.sqlite3"]["sqlite_tables"] == expected
    assert validation["temporary_copy_removed"]
    # A distinct, freshly created copy is reopened to check business relations.
    recovered = tmp_path / "independent-recovery"
    recovered.mkdir()
    for name, content in files.items():
        target = recovered / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(content)
    with closing(sqlite3.connect((recovered / "business.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert sqlite_fingerprint(db) == expected
        assert db.execute("SELECT status FROM delivery_demands WHERE id=?", (data["morning"],)).fetchone() == ("COMPLETED",)
        assert db.execute("SELECT delivery_status FROM dispatch_order_details WHERE id=?", (data["stop"],)).fetchone() == ("SIGNED",)
        assert db.execute("SELECT review_status FROM delivery_proofs").fetchone() == ("APPROVED",)
        assert db.execute("SELECT decision FROM delivery_proof_reviews").fetchone() == ("APPROVED",)
        assert db.execute("SELECT COUNT(*) FROM audit_logs WHERE action='DELIVERY_STOP_SIGNED'").fetchone()[0] == 1
    for name in proof_paths:
        assert (recovered / "uploads" / name).read_bytes() == (upload_root / name).read_bytes()
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == snapshot_sha
    assert archive_path.read_bytes() == payload
    (tmp_path / "BUSINESS_RESTORE_EVIDENCE.json").write_text(json.dumps({
        "source":"new synthetic in-memory fixture", "snapshot":str(snapshot),
        "target":str(recovered), "snapshot_sha256":snapshot_sha,
        "archive_sha256":hashlib.sha256(payload).hexdigest(),"table_count":len(expected),
        "logical_table_fingerprints":expected,"proofs":len(proof_paths),
        "completed_signed_approved_and_audit_verified":True,
        "source_snapshot_and_archive_bytes_unchanged":True,
        "mysql_restore":"NOT RUN", "linux_ownership":"NOT VERIFIED ON WINDOWS",
    },ensure_ascii=False,indent=2),encoding="utf-8")


def test_private_http_start_stop_and_sqlite_reopen(tmp_path):
    import httpx
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    import uvicorn
    from app.domain.enums import UserRole
    from app.infrastructure.database.base import Base
    from app.infrastructure.database.session import get_db
    from app.main import app
    from app.services.auth_service import AuthService

    database = tmp_path / "http-smoke.sqlite3"
    url = "sqlite+pysqlite:///" + database.as_posix()
    engine = create_engine(url, connect_args={"check_same_thread":False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        AuthService(db).create_user("task3-http-admin","SyntheticTask3Pass!123",UserRole.ADMIN)
    previous = app.dependency_overrides.copy()
    def private_db():
        with Session(engine,expire_on_commit=False) as db:
            yield db
    app.dependency_overrides[get_db] = private_db
    phases=[]
    try:
        for phase in (1,2):
            listener=socket.socket();listener.bind(("127.0.0.1",0))
            port=listener.getsockname()[1]
            server=uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=port,
                lifespan="on",access_log=False,log_config=None))
            thread=threading.Thread(target=server.run,kwargs={"sockets":[listener]},daemon=True)
            thread.start()
            try:
                deadline=time.monotonic()+10
                while not server.started and thread.is_alive() and time.monotonic()<deadline:
                    time.sleep(0.02)
                assert server.started,"private HTTP server failed to start"
                with httpx.Client(base_url=f"http://127.0.0.1:{port}",timeout=5,trust_env=False) as http:
                    health=http.get("/health");ready=http.get("/health/ready")
                    assert health.status_code==ready.status_code==200
                    denied=http.get("/api/v1/stores");assert denied.status_code==401
                    login=http.post("/api/v1/auth/login",json={"username":"task3-http-admin","password":"SyntheticTask3Pass!123"})
                    assert login.status_code==200
                    http.headers["Authorization"]="Bearer "+login.json()["access_token"]
                    if phase==1:
                        payload={"code":"TASK3_HTTP","name":"合成HTTP门店"}
                        assert http.post("/api/v1/stores",json=payload).status_code==201
                        assert http.post("/api/v1/stores",json=payload).status_code==409
                    stores=http.get("/api/v1/stores")
                    assert stores.status_code==200 and stores.json()[0]["code"]=="TASK3_HTTP"
                    phases.append({"phase":phase,"host":"127.0.0.1","port":port,
                        "health":health.status_code,"ready":ready.status_code,
                        "unauthenticated":denied.status_code,"login":login.status_code,
                        "store_persisted":True})
            finally:
                server.should_exit=True;thread.join(10);listener.close()
                assert not thread.is_alive(),"private HTTP server failed to stop"
            engine.dispose()
            if phase==1:
                engine=create_engine(url,connect_args={"check_same_thread":False})
    finally:
        app.dependency_overrides.clear();app.dependency_overrides.update(previous)
        engine.dispose()
    (tmp_path / "HTTP_LIFECYCLE_EVIDENCE.json").write_text(json.dumps({
        "database":str(database),"type":"synthetic SQLite only","phases":phases,
        "server_threads_stopped":True,"mysql_restart":"NOT RUN","docker":"NOT USED",
    },ensure_ascii=False,indent=2),encoding="utf-8")
