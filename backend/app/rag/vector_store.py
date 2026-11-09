from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from app.rag.exceptions import KnowledgeBaseNotReadyError
from app.rag.schemas import KnowledgeChunk, KnowledgeSearchResult


class ChromaVectorStore:
    def __init__(self, persist_directory: str | Path, collection_name: str) -> None:
        self.persist_directory = Path(persist_directory)
        self.collection_name = collection_name

    def rebuild(
        self, chunks: list[KnowledgeChunk], embeddings: list[list[float]]
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        client = self._client(create_directory=True)
        # Standalone callers also build a new collection; never delete a live index.
        self.collection_name = f"{self.collection_name[:30]}_{uuid4().hex}"
        collection = client.get_or_create_collection(
            self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        if not chunks:
            return
        collection.add(
            ids=[
                chunk.chunk_id or f"{chunk.source}:{chunk.chunk_index}"
                for chunk in chunks
            ],
            documents=[chunk.content for chunk in chunks],
            embeddings=embeddings,
            metadatas=[self._metadata(chunk) for chunk in chunks],
        )

    def search(
        self,
        query_embedding: list[float],
        top_k: int,
        document_type: str | None = None,
        allowed_ids: set[str] | None = None,
    ) -> list[KnowledgeSearchResult]:
        collection = self._existing_collection()
        if collection.count() == 0:
            return []
        where = {"document_type": document_type} if document_type else None
        if allowed_ids is not None and not allowed_ids:
            return []
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(
                top_k,
                collection.count(),
                len(allowed_ids) if allowed_ids is not None else collection.count(),
            ),
            where=where,
            **({"ids": sorted(allowed_ids)} if allowed_ids is not None else {}),
            include=["documents", "metadatas", "distances"],
        )
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        ids = (result.get("ids") or [[]])[0]
        items: list[KnowledgeSearchResult] = []
        for chunk_id, content, metadata, distance in zip(
            ids, documents, metadatas, distances
        ):
            if not isinstance(content, str) or not isinstance(metadata, dict):
                continue
            items.append(
                KnowledgeSearchResult(
                    content=content,
                    source=str(metadata["source"]),
                    document_name=str(metadata["document_name"]),
                    document_id=str(metadata.get("document_id", metadata["source"])),
                    document_type=str(metadata["document_type"]),
                    section=str(metadata["section"]),
                    chunk_index=int(metadata["chunk_index"]),
                    chunk_id=chunk_id,
                    access_scope=str(metadata.get("access_scope", "public")),
                    index_version=metadata.get("index_version"),
                    vector_distance=float(distance),
                    score=max(0.0, min(1.0, 1.0 - float(distance))),
                )
            )
        return items

    def status(self) -> tuple[int, int]:
        collection = self._existing_collection()
        count = collection.count()
        if count == 0:
            return 0, 0
        result = collection.get(include=["metadatas"])
        metadata = result.get("metadatas") or []
        documents = len({item.get("source") for item in metadata if item})
        return documents, count

    def _existing_collection(self):
        if not self.persist_directory.is_dir():
            raise KnowledgeBaseNotReadyError("知识库尚未初始化，请先运行知识库构建命令")
        client = self._client(create_directory=False)
        try:
            return client.get_collection(self.collection_name)
        except Exception as exc:
            if exc.__class__.__name__ in {
                "NotFoundError",
                "InvalidCollectionException",
            }:
                raise KnowledgeBaseNotReadyError(
                    "知识库尚未初始化，请先运行知识库构建命令"
                ) from None
            raise

    def _client(self, *, create_directory: bool):
        if create_directory:
            self.persist_directory.mkdir(parents=True, exist_ok=True)
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
        except ImportError:
            raise KnowledgeBaseNotReadyError("Chroma 依赖未安装") from None
        return chromadb.PersistentClient(
            path=str(self.persist_directory),
            settings=ChromaSettings(anonymized_telemetry=False),
        )

    @staticmethod
    def _metadata(chunk: KnowledgeChunk) -> dict[str, Any]:
        return {
            "source": chunk.source,
            "document_id": chunk.document_id or chunk.source,
            "document_name": chunk.document_name,
            "document_type": chunk.document_type,
            "section": chunk.section,
            "chunk_index": chunk.chunk_index,
            "access_scope": chunk.access_scope,
            "index_version": chunk.index_version or "legacy",
        }
