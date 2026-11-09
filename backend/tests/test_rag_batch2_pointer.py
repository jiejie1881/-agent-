"""Event-controlled Windows sharing regression; only pytest-owned files."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Thread, current_thread

import pytest

pytestmark = pytest.mark.usefixtures("batch2_guard_attestation")

from app.rag.exceptions import KnowledgeBaseNotReadyError
from app.rag.versioned_index import VersionedIndex
from app.rag.rag_service import RagService
from app.rag.vector_store import ChromaVectorStore


def service(tmp_path):
    """Standalone synthetic corpus, with no Agent/ORM/test-conftest imports."""
    from types import SimpleNamespace

    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "dispatch_rules.md").write_text("车辆出勤派车规则。", encoding="utf-8")
    embedding = SimpleNamespace(
        embed_documents=lambda texts: [[1.0, 0.1] for _ in texts],
        embed_query=lambda query: [1.0, 0.1],
    )
    return RagService(
        embedding,
        ChromaVectorStore(tmp_path / "index", "batch2"),
        knowledge_base_dir=str(knowledge),
        retrieval_mode="hybrid",
    )


def test_open_pointer_reader_does_not_block_atomic_activation(tmp_path, monkeypatch):
    assert os.name == "nt", "Windows-specific regression must run on Windows"
    rag = service(tmp_path)
    rag.rebuild()
    old = rag.last_built_version
    rag.rebuild(activate=False, reuse_embeddings=True)
    new = rag.last_built_version
    ready, release, finished = Event(), Event(), Event()
    outcomes, errors = [], []
    pointer = rag.versions.root / "active.json"
    native_open, native_fdopen = Path.open, os.fdopen

    class HeldReader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def read(self, *args):
            ready.set()
            assert release.wait(10), "reader release missing"
            return self.stream.read(*args)

    def opened(path, *a, **kw):
        stream = native_open(path, *a, **kw)
        return (
            HeldReader(stream)
            if path == pointer and current_thread().name == "held-reader"
            else stream
        )

    def fdopened(*a, **kw):
        stream = native_fdopen(*a, **kw)
        return (
            HeldReader(stream)
            if current_thread().name == "held-reader" and not ready.is_set()
            else stream
        )

    monkeypatch.setattr(Path, "open", opened)
    monkeypatch.setattr(os, "fdopen", fdopened)

    def reader():
        try:
            outcomes.append(rag.versions.load()[0]["version"])
        except BaseException as error:
            errors.append(error)

    def writer():
        try:
            rag.versions.activate(
                new, expected_active_version=old, configuration=rag._configuration()
            )
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()

    r = Thread(target=reader, name="held-reader")
    w = Thread(target=writer, name="pointer-writer")
    r.start()
    try:
        assert ready.wait(5), "reader never acquired file handle"
        w.start()
        assert finished.wait(5), (
            "writer must finish while old reader handle remains open"
        )
    finally:
        release.set()
        r.join(10)
        if w.ident is not None:
            w.join(10)
    assert not r.is_alive() and not w.is_alive()
    if errors:
        raise errors[0]
    assert outcomes == [old]
    assert rag.versions.load()[0]["version"] == new
    assert not list(rag.versions.root.glob("*.tmp"))


def test_atomic_replace_failure_retains_old_complete_pointer(tmp_path, monkeypatch):
    pointer = tmp_path / "active.json"
    VersionedIndex._write(pointer, {"manifest": "old.json"})
    before = pointer.read_bytes()

    def denied(*args):
        raise PermissionError("synthetic sharing violation")

    monkeypatch.setattr("app.rag.versioned_index.atomic_replace", denied)
    with pytest.raises(PermissionError):
        VersionedIndex._write(pointer, {"manifest": "new.json"})
    assert pointer.read_bytes() == before
    assert json.loads(before) == {"manifest": "old.json"}
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize(
    "payload", ["{", '{"manifest":"../foreign.json"}', '{"manifest":"absent.json"}']
)
def test_bad_pointer_fails_closed_without_repair(tmp_path, payload):
    rag = service(tmp_path)
    rag.rebuild()
    pointer = rag.versions.root / "active.json"
    pointer.write_text(payload, encoding="utf-8")
    with pytest.raises(KnowledgeBaseNotReadyError):
        rag.versions.load()
    assert pointer.read_text(encoding="utf-8") == payload


@pytest.mark.parametrize("iteration", range(3))
def test_readers_pin_versions_during_twenty_reads_and_four_switches(
    tmp_path, iteration
):
    rag = service(tmp_path)
    rag.rebuild()
    old = rag.last_built_version
    rag.rebuild(activate=False, reuse_embeddings=True)
    new = rag.last_built_version

    def read(_):
        hits = rag.search("车辆出勤")
        assert len({h.index_version for h in hits}) == 1
        assert hits[0].index_version in {old, new}

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(read, i) for i in range(20)]
        active = old
        for target in (new, old, new, old):
            rag.versions.activate(
                target,
                expected_active_version=active,
                configuration=rag._configuration(),
            )
            active = target
        for future in futures:
            future.result(timeout=30)


def test_failed_flush_never_exposes_partial_pointer(tmp_path, monkeypatch):
    pointer = tmp_path / "active.json"
    VersionedIndex._write(pointer, {"manifest": "old.json"})
    before = pointer.read_bytes()

    def failed_flush(*args):
        raise OSError("synthetic flush failure")

    monkeypatch.setattr(os, "fsync", failed_flush)
    with pytest.raises(OSError):
        VersionedIndex._write(pointer, {"manifest": "new.json"})
    assert pointer.read_bytes() == before
    assert list(tmp_path.glob("*.tmp")) == []


def test_shared_reader_closes_handle_after_invalid_utf8(tmp_path, monkeypatch):
    from app.rag.versioned_index import read_text_shared

    path = tmp_path / "invalid.json"
    path.write_bytes(b"\xff")
    descriptors = []
    original = os.fdopen

    def record_open(fd, *args, **kwargs):
        descriptors.append(fd)
        return original(fd, *args, **kwargs)

    monkeypatch.setattr(os, "fdopen", record_open)
    with pytest.raises(UnicodeError):
        read_text_shared(path)
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
    with path.open("wb") as stream:
        stream.write(b"valid")
    assert read_text_shared(path) == "valid"


def test_shared_handle_allows_replace_before_close(tmp_path, monkeypatch):
    from app.rag.versioned_index import read_text_shared

    path = tmp_path / "active.json"
    VersionedIndex._write(path, {"manifest": "old.json"})
    original = os.fdopen

    def open_then_replace(*a, **kw):
        stream = original(*a, **kw)
        VersionedIndex._write(path, {"manifest": "new.json"})
        return stream

    monkeypatch.setattr(os, "fdopen", open_then_replace)
    assert json.loads(read_text_shared(path)) == {"manifest": "old.json"}
    assert json.loads(path.read_text("utf-8")) == {"manifest": "new.json"}


def test_native_rename_invalid_destination_preserves_source_and_old_pointer(tmp_path):
    from app.rag.versioned_index import atomic_replace

    pointer = tmp_path / "active.json"
    VersionedIndex._write(pointer, {"manifest": "old.json"})
    candidate = tmp_path / "candidate.json"
    candidate.write_bytes(b"candidate")
    with pytest.raises(OSError):
        atomic_replace(candidate, tmp_path / "missing-parent" / "active.json")
    assert candidate.read_bytes() == b"candidate"
    assert json.loads(pointer.read_text("utf-8")) == {"manifest": "old.json"}


def test_fdopen_failure_preserves_error_and_closes_native_handle(tmp_path, monkeypatch):
    from app.rag.versioned_index import read_text_shared

    path = tmp_path / "reader.json"
    path.write_text("valid", encoding="utf-8")

    descriptors = []

    def failed_open(fd, *args, **kwargs):
        descriptors.append(fd)
        raise ValueError("synthetic descriptor conversion failure")

    monkeypatch.setattr(os, "fdopen", failed_open)
    with pytest.raises(ValueError, match="descriptor conversion"):
        read_text_shared(path)
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
    path.unlink()
    assert not path.exists()


@pytest.mark.parametrize("long_path", [False, True])
def test_unicode_and_extended_length_paths(tmp_path, long_path):
    from app.rag.versioned_index import read_text_shared

    parent = tmp_path
    if long_path:
        parent = parent / ("a" * 80) / ("b" * 80) / ("c" * 80)
        parent.mkdir(parents=True)
    path = parent / "版本🚚.json"
    VersionedIndex._write(path, {"manifest": "old.json"})
    VersionedIndex._write(path, {"manifest": "new.json"})
    assert json.loads(read_text_shared(path)) == {"manifest": "new.json"}


@pytest.mark.parametrize("padding", range(8))
def test_native_rename_filename_length_does_not_depend_on_struct_padding(
    tmp_path, padding
):
    from app.rag.versioned_index import read_text_shared

    path = tmp_path / ("版本🚚" + "x" * padding + ".json")
    VersionedIndex._write(path, {"manifest": "old.json"})
    VersionedIndex._write(path, {"manifest": "new.json"})
    assert json.loads(read_text_shared(path)) == {"manifest": "new.json"}
