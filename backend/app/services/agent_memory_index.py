"""长期记忆向量索引（Chroma 派生投影）。

隔离策略：**每个项目 + 每个 embedding 版本一个独立 collection**，集合名形如
``logistics_memory__<embedding_version>``，并写入 ``project_id`` /
``embedding_version`` / ``purpose`` 元数据；打开集合时若元数据不一致直接报错，
从结构上禁止不同维度或模型版本的向量混用。

MySQL 是权威来源：本模块只负责写入/删除/查询向量，状态判定一律回到 MySQL 复核。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

MEMORY_PURPOSE = "agent_long_term_memory"
_COLLECTION_MAX = 63

_NAME_SAFE = re.compile(r"[^a-zA-Z0-9_-]+")


class MemoryIndexMismatchError(RuntimeError):
    """集合已有的 embedding 版本与当前配置不一致：禁止混用不同模型/维度。"""


def _sanitize(name: str) -> str:
    cleaned = _NAME_SAFE.sub("_", name).strip("_")
    if len(cleaned) < 3:
        cleaned = f"m_{cleaned}"
    if len(cleaned) <= _COLLECTION_MAX:
        return cleaned
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned[: _COLLECTION_MAX - 9]}_{digest}"


def collection_name(project_id: str, embedding_version: str) -> str:
    return _sanitize(f"{project_id}__memory__{embedding_version}")


class MemoryIndex:
    """Chroma collection 的薄封装（与 chromadb.Collection 方法名保持一致）。"""

    def __init__(self, collection, *, project_id: str, embedding_version: str,
                 client=None, name: str | None = None) -> None:
        self.collection = collection
        self.project_id = project_id
        self.embedding_version = embedding_version
        self._client = client
        self._name = name or getattr(collection, "name", None)

    # ---- 与 chromadb.Collection 兼容的最小接口 ----
    def count(self) -> int:
        return int(self.collection.count())

    def upsert(self, *, ids, embeddings, metadatas=None, documents=None) -> None:
        metadatas = list(metadatas or [{} for _ in ids])
        for meta in metadatas:
            meta.setdefault("project_id", self.project_id)
            meta.setdefault("embedding_version", self.embedding_version)
        kwargs: dict[str, Any] = {
            "ids": list(ids),
            "embeddings": [list(vector) for vector in embeddings],
            "metadatas": metadatas,
        }
        if documents is not None:
            kwargs["documents"] = list(documents)
        self.collection.upsert(**kwargs)

    def delete(self, *, ids) -> None:
        ids = list(ids)
        if ids:
            self.collection.delete(ids=ids)

    def query(self, *, query_embeddings, n_results, where=None, include=None) -> dict:
        return self.collection.query(
            query_embeddings=query_embeddings,
            n_results=n_results,
            where=where,
            include=include or ["metadatas", "distances"],
        )

    def get(self, *, where=None, limit=None, include=None) -> dict:
        kwargs: dict[str, Any] = {"include": include or ["metadatas"]}
        if where is not None:
            kwargs["where"] = where
        if limit is not None:
            kwargs["limit"] = limit
        return self.collection.get(**kwargs)

    def reset(self) -> None:
        """删除并重建本集合（索引重建专用）。"""
        if self._client is not None and self._name:
            try:
                self._client.delete_collection(self._name)
            except Exception:  # noqa: BLE001 - 集合不存在时忽略
                pass
            self.collection = self._client.get_or_create_collection(
                name=self._name, metadata=self._metadata()
            )
            return
        # 兜底：没有客户端引用时逐条清空（测试用原生 collection）
        ids = (self.collection.get(include=[]) or {}).get("ids") or []
        if ids:
            self.collection.delete(ids=ids)

    def _metadata(self) -> dict:
        return {
            "purpose": MEMORY_PURPOSE,
            "project_id": self.project_id,
            "embedding_version": self.embedding_version,
            "hnsw:space": "cosine",
        }


def build_memory_index(*, persist_dir: str, project_id: str, embedding_version: str) -> MemoryIndex:
    """按 项目 + embedding 版本 打开（或创建）独立 collection。"""
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    client = chromadb.PersistentClient(
        path=persist_dir, settings=ChromaSettings(anonymized_telemetry=False)
    )
    name = collection_name(project_id, embedding_version)
    metadata = {
        "purpose": MEMORY_PURPOSE,
        "project_id": project_id,
        "embedding_version": embedding_version,
        "hnsw:space": "cosine",
    }
    try:
        collection = client.get_or_create_collection(name=name, metadata=metadata)
    except ValueError as exc:  # 已存在但 metadata 不同：Chroma 直接拒绝
        raise MemoryIndexMismatchError(f"集合 {name} 元数据与当前配置不一致：{exc}") from None
    existing = collection.metadata or {}
    if existing.get("embedding_version") not in (None, embedding_version):
        raise MemoryIndexMismatchError(
            f"集合 {name} 已有模型版本 {existing.get('embedding_version')}，"
            f"与当前配置 {embedding_version} 不一致（禁止不同模型版本混用）"
        )
    return MemoryIndex(collection, project_id=project_id, embedding_version=embedding_version,
                       client=client, name=name)
