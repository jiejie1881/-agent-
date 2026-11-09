from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.rag.exceptions import KnowledgeBaseNotReadyError
from app.rag.schemas import KnowledgeChunk
from app.rag.vector_store import ChromaVectorStore


def encoded(value) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(encoded(value)).hexdigest()


def _windows_path(path: Path) -> str:
    absolute = os.path.abspath(path)
    if absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def read_text_shared(path: Path) -> str:
    """Read a pinned file while allowing atomic replacement on Windows.

    Python's ordinary Windows file opens do not share deletion. The old handle
    must remain readable after rename, so readers explicitly share deletion;
    they still read one complete immutable file, never a partially written one.
    """
    if os.name != "nt":
        return path.read_text(encoding="utf-8")
    import ctypes
    from ctypes import wintypes
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    # GENERIC_READ; SHARE_READ | SHARE_WRITE | SHARE_DELETE; OPEN_EXISTING.
    handle = create(_windows_path(path), 0x80000000, 0x7, None, 3, 0x80, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        close(handle)
        raise
    try:
        stream = os.fdopen(fd, "r", encoding="utf-8")
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass  # fdopen may already have consumed/closed the descriptor.
        raise
    with stream:
        return stream.read()


def atomic_replace(source: Path, target: Path) -> None:
    """Rename in one operation, allowing old Windows handles to remain pinned.

    Windows requires POSIX rename semantics to replace an open destination.
    Unsupported filesystems/OS versions fail closed; no delete-then-rename or
    ReplaceFile fallback can expose a temporary missing active pointer.
    """
    if os.name != "nt":
        os.replace(source, target)
        return
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    rename = kernel.SetFileInformationByHandle
    rename.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    rename.restype = wintypes.BOOL
    name = _windows_path(target).encode("utf-16-le")

    class RenameInfo(ctypes.Structure):
        _fields_ = [
            ("flags", wintypes.DWORD),
            ("root", wintypes.HANDLE),
            ("length", wintypes.DWORD),
            ("name", ctypes.c_byte * (len(name) + 2)),
        ]

    info = RenameInfo()
    info.flags = 0x1 | 0x2  # REPLACE_IF_EXISTS | POSIX_SEMANTICS
    info.length = len(name)
    # The Win32 wrapper also needs a trailing wide NUL. Relying on structure
    # alignment padding makes path validity depend on the filename's length.
    ctypes.memmove(ctypes.addressof(info) + RenameInfo.name.offset, name, len(name))
    handle = create(
        _windows_path(source), 0x10000, 0x7, None, 3, 0x80, None
    )  # DELETE access
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not rename(
            handle, 22, ctypes.byref(info), ctypes.sizeof(info)
        ):  # FileRenameInfoEx
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        close(handle)


class VersionedIndex:
    """Immutable shared corpus with an atomic pointer. Never alters legacy collections."""

    def __init__(self, store: ChromaVectorStore):
        self.store = store
        self.root = store.persist_directory / "hybrid" / store.collection_name

    def publish(self, chunks, embeddings, configuration, *, before_activate=None, activate=True) -> str:
        dimensions={len(v) for v in embeddings}
        if len(chunks)!=len(embeddings) or len(dimensions)!=1 or not all(dimensions) or any(
            not math.isfinite(float(v)) for row in embeddings for v in row
        ):
            raise KnowledgeBaseNotReadyError('向量维度或数值无效，未切换索引')
        self.root.mkdir(parents=True, exist_ok=True)
        lock = self.root / "build.lock"
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise KnowledgeBaseNotReadyError("知识库正在构建，拒绝并发切换") from None
        try:
            os.close(handle)
            version = uuid4().hex
            chunks = [
                chunk.model_copy(update={"index_version": version}) for chunk in chunks
            ]
            candidate = ChromaVectorStore(
                self.store.persist_directory, self.store.collection_name
            )
            candidate.rebuild(chunks, embeddings)
            stored=candidate._existing_collection().get(include=['embeddings'])
            payload = {
                "manifest_schema": 2,
                "embedding_dimension": next(iter(dimensions)),
                "embedding_sha256": digest({key:[float(v) for v in row] for key,row in zip(stored['ids'],stored['embeddings'])}),
                "version": version,
                "collection": candidate.collection_name,
                "configuration": configuration,
                "generated_at": datetime.now(UTC).isoformat(),
                "status": "validated",
                "chunk_count": len(chunks),
                "document_count": len({c.source for c in chunks}),
                "dataset_sha256": digest([c.model_dump() for c in chunks]),
                "chunks": [c.model_dump() for c in chunks],
            }
            manifest = {"payload": payload, "sha256": digest(payload)}
            target = self.root / f"{version}.json"
            self._write(target, manifest)
            _, validated, store = self._read(target)
            self.validate_vector(validated, store)
            if before_activate is not None:
                before_activate()
            if activate:
                self._write(self.root / "active.json", {"manifest": target.name})
            return version
        finally:
            lock.unlink()

    def activate(self, version, *, expected_active_version, configuration):
        """Explicit CAS activation/rollback; never deletes a retained collection."""
        if len(version)!=32 or any(c not in '0123456789abcdef' for c in version):
            raise KnowledgeBaseNotReadyError('非法索引版本')
        lock=self.root/'build.lock'
        try:
            handle=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        except FileExistsError:
            raise KnowledgeBaseNotReadyError('知识库正在构建或切换') from None
        try:
            os.close(handle)
            active=self.load()
            current=active[0]['version'] if active else None
            if current!=expected_active_version:
                raise KnowledgeBaseNotReadyError('活动索引已变化，拒绝覆盖')
            payload,chunks,store=self._read(self.root/(version+'.json'))
            if payload['configuration']!=configuration:
                raise KnowledgeBaseNotReadyError('候选索引配置不兼容，需要匹配代码与模型')
            self.validate_vector(chunks,store)
            self._write(self.root/'active.json',{'manifest':version+'.json'})
            return version
        finally:
            lock.unlink()

    @staticmethod
    def _write(target: Path, value):
        temporary = target.with_name(target.name + "." + uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(encoded(value))
                stream.flush()
                os.fsync(stream.fileno())
            atomic_replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def load(self):
        pointer = self.root / "active.json"
        if not pointer.exists():
            return None
        try:
            name = json.loads(read_text_shared(pointer))["manifest"]
            if Path(name).name != name or not name.endswith(".json"):
                raise ValueError("Invalid pointer")
            return self._read(self.root / name)
        except Exception:  # noqa: BLE001 - malformed or unavailable manifest must fail closed.
            raise KnowledgeBaseNotReadyError(
                "知识库版本或权限元数据不一致，检索已停止"
            ) from None

    def _read(self, path):
        manifest = json.loads(read_text_shared(path))
        payload = manifest["payload"]
        if payload.get('manifest_schema',1) not in {1,2} or payload['status']!='validated':
            raise ValueError('Unsupported manifest schema/status')
        if digest(payload) != manifest["sha256"]:
            raise ValueError("Manifest checksum mismatch")
        chunks = [KnowledgeChunk.model_validate(c) for c in payload["chunks"]]
        if payload["chunk_count"] != len(chunks) or payload["dataset_sha256"] != digest(
            payload["chunks"]
        ):
            raise ValueError("Dataset checksum mismatch")
        by_id = {c.chunk_id: c for c in chunks}
        if len(by_id) != len(chunks) or not all(by_id) or any(c.index_version!=payload['version'] for c in chunks):
            raise ValueError("Invalid shared IDs")
        store = ChromaVectorStore(self.store.persist_directory, payload["collection"])
        store.expected_embedding_dimension=payload.get('embedding_dimension')
        store.expected_embedding_sha256=payload.get('embedding_sha256')
        # A manifest is durable even when the vector service is temporarily unavailable.
        return payload, chunks, store

    @staticmethod
    def validate_vector(chunks, store):
        actual = store._existing_collection().get(include=["documents", "metadatas", "embeddings"])
        expected = {c.chunk_id: c for c in chunks}
        if set(actual["ids"]) != set(expected) or any(
            len(actual[key])!=len(expected) for key in ('ids','documents','metadatas','embeddings')
        ):
            raise KnowledgeBaseNotReadyError("知识库两路版本不一致")
        for key, content, metadata in zip(
            actual["ids"], actual["documents"], actual["metadatas"]
        ):
            chunk = expected[key]
            if content != chunk.content or metadata != store._metadata(chunk):
                raise KnowledgeBaseNotReadyError("知识库两路权限或内容不一致")
        vectors={key:[float(v) for v in row] for key,row in zip(actual['ids'],actual['embeddings'])}
        dimensions={len(v) for v in vectors.values()}
        dimension=getattr(store,'expected_embedding_dimension',None)
        checksum=getattr(store,'expected_embedding_sha256',None)
        if len(dimensions)!=1 or not all(dimensions) or (dimension is not None and dimensions!={dimension}) or any(
            not math.isfinite(v) for row in vectors.values() for v in row
        ) or (checksum is not None and digest(vectors)!=checksum):
            raise KnowledgeBaseNotReadyError('知识库向量维度或指纹不一致')
