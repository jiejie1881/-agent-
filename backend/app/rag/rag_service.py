from __future__ import annotations

from app.rag.document_loader import KnowledgeDocumentLoader
from app.rag.embedding_client import EmbeddingClient
from app.rag.exceptions import KnowledgeBaseError
from app.rag.schemas import (
    KnowledgeBaseStatus,
    KnowledgeBuildResult,
    KnowledgeSearchResult,
)
from app.rag.splitter import KnowledgeTextSplitter
from app.rag.vector_store import ChromaVectorStore


class RagService:
    def __init__(
        self,
        embedding_client: EmbeddingClient,
        vector_store: ChromaVectorStore,
        *,
        knowledge_base_dir: str,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
        default_top_k: int = 4,
        loader: KnowledgeDocumentLoader | None = None,
    ) -> None:
        self.embedding_client = embedding_client
        self.vector_store = vector_store
        self.knowledge_base_dir = knowledge_base_dir
        self.default_top_k = default_top_k
        self.loader = loader or KnowledgeDocumentLoader()
        self.splitter = KnowledgeTextSplitter(chunk_size, chunk_overlap)

    def rebuild(self) -> KnowledgeBuildResult:
        sections = self.loader.load_directory(self.knowledge_base_dir)
        chunks = self.splitter.split(sections)
        embeddings = self.embedding_client.embed_documents(
            [chunk.content for chunk in chunks]
        )
        self.vector_store.rebuild(chunks, embeddings)
        return KnowledgeBuildResult(
            documents=len({chunk.source for chunk in chunks}),
            chunks=len(chunks),
        )

    def search(
        self,
        query: str,
        top_k: int | None = None,
        document_type: str | None = None,
    ) -> list[KnowledgeSearchResult]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("知识库查询不能为空")
        limit = top_k or self.default_top_k
        query_embedding = self.embedding_client.embed_query(normalized_query)
        return self.vector_store.search(query_embedding, limit, document_type)

    def status(self) -> KnowledgeBaseStatus:
        try:
            documents, chunks = self.vector_store.status()
        except KnowledgeBaseError:
            return KnowledgeBaseStatus(ready=False, documents=0, chunks=0)
        return KnowledgeBaseStatus(
            ready=chunks > 0,
            documents=documents,
            chunks=chunks,
        )
