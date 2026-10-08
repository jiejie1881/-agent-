from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest

from app.agent.exceptions import AgentToolArgumentsError, AgentToolExecutionError
from app.agent.knowledge_tools import SearchKnowledgeBaseTool
from app.agent.tool_execution import AgentToolContext, AgentToolExecutorRegistry
from app.agent.tool_registry import AgentToolRegistry
from app.core.config import Settings
from app.domain.enums import UserRole
from app.models.user import User
from app.rag.document_loader import KnowledgeDocumentLoader
from app.rag.embedding_client import EmbeddingClient, OpenAICompatibleEmbeddingClient
from app.rag.exceptions import KnowledgeBaseNotReadyError
from app.rag.exceptions import KnowledgeBaseConfigurationError
from app.rag.rag_service import RagService
from app.rag.schemas import KnowledgeSection
from app.rag.splitter import KnowledgeTextSplitter
from app.rag.vector_store import ChromaVectorStore


class KeywordEmbeddingClient(EmbeddingClient):
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    @staticmethod
    def _vector(text: str) -> list[float]:
        return [
            float(sum(word in text for word in ("冷冻", "冷链", "温度"))),
            float(sum(word in text for word in ("异常", "未分配", "失败"))),
            0.1,
        ]


def build_service(tmp_path: Path, knowledge_dir: Path) -> RagService:
    return RagService(
        KeywordEmbeddingClient(),
        ChromaVectorStore(tmp_path / "chroma", "test_knowledge"),
        knowledge_base_dir=str(knowledge_dir),
        chunk_size=80,
        chunk_overlap=10,
    )


def test_markdown_and_text_loading_preserves_metadata(tmp_path: Path) -> None:
    (tmp_path / "cold_chain_rules.md").write_text(
        "# 冷链规则\n\n## 车辆要求\n冷冻货物需要温控能力。",
        encoding="utf-8",
    )
    (tmp_path / "manual.txt").write_text("系统操作说明", encoding="utf-8")

    sections = KnowledgeDocumentLoader().load_directory(tmp_path)

    cold = next(item for item in sections if item.source == "cold_chain_rules.md")
    assert cold.document_type == "cold_chain"
    assert cold.section == "车辆要求"
    assert any(item.document_type == "system_manual" for item in sections)


def test_invalid_document_does_not_hide_other_valid_documents(tmp_path: Path) -> None:
    (tmp_path / "valid.txt").write_text("可用知识", encoding="utf-8")
    (tmp_path / "broken.md").write_bytes(b"\xff\xfe\x00")

    sections = KnowledgeDocumentLoader().load_directory(tmp_path)

    assert [item.source for item in sections] == ["valid.txt"]


def test_splitter_preserves_source_section_and_chunk_indexes() -> None:
    section = KnowledgeSection(
        content="冷链规则。" * 40,
        source="cold.md",
        document_name="cold",
        document_type="cold_chain",
        section="温控",
    )

    chunks = KnowledgeTextSplitter(60, 10).split([section])

    assert len(chunks) > 1
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.source == "cold.md" and chunk.section == "温控" for chunk in chunks)


def test_chroma_rebuild_and_search_returns_real_source(tmp_path: Path) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "cold_chain_rules.md").write_text(
        "# 冷链\n\n## 能力\n冷冻货物必须使用具备冷链温控能力的车辆。",
        encoding="utf-8",
    )
    (knowledge / "exception_handling.md").write_text(
        "# 异常\n\n## 未分配\n未分配需求应保留原因。",
        encoding="utf-8",
    )
    service = build_service(tmp_path, knowledge)

    built = service.rebuild()
    results = service.search("冷冻货物温度要求", top_k=1)

    assert built.documents == 2
    assert built.chunks == 2
    assert results[0].source == "cold_chain_rules.md"
    assert results[0].document_type == "cold_chain"
    assert 0 <= results[0].score <= 1
    assert service.status().ready is True


def test_document_type_filter_and_no_results(tmp_path: Path) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "cold_chain_rules.md").write_text("# 冷链\n冷冻温控要求。", encoding="utf-8")
    service = build_service(tmp_path, knowledge)
    service.rebuild()

    assert service.search("冷冻", document_type="exception_manual") == []


def test_empty_query_and_missing_vector_store_are_safe(tmp_path: Path) -> None:
    service = RagService(
        KeywordEmbeddingClient(),
        ChromaVectorStore(tmp_path / "missing", "missing"),
        knowledge_base_dir=str(tmp_path),
    )

    with pytest.raises(ValueError, match="不能为空"):
        service.search("  ")
    with pytest.raises(KnowledgeBaseNotReadyError, match="尚未初始化"):
        service.search("冷链要求")
    assert service.status().ready is False


def test_openai_compatible_embedding_client_parses_ordered_vectors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json={"data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}]},
        )

    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        jwt_secret_key="x" * 32,
        rag_embedding_provider="openai-compatible",
        rag_embedding_model="demo-embedding",
        rag_embedding_api_key="secret",
        rag_embedding_base_url="https://embedding.example/v1",
    )
    client = OpenAICompatibleEmbeddingClient(settings, httpx.MockTransport(handler))

    assert client.embed_documents(["文档A", "文档B"]) == [[1.0, 0.0], [0.0, 1.0]]


def test_embedding_configuration_error_is_safe() -> None:
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        jwt_secret_key="x" * 32,
        rag_embedding_provider=None,
        rag_embedding_model=None,
        rag_embedding_api_key=None,
        rag_embedding_base_url=None,
    )

    with pytest.raises(KnowledgeBaseConfigurationError, match="Provider"):
        OpenAICompatibleEmbeddingClient(settings).embed_query("冷链")


def test_knowledge_tool_schema_registry_execution_and_safe_error(tmp_path: Path) -> None:
    registry = AgentToolRegistry()
    definition = registry.get("search_knowledge_base")
    assert definition.read_only is True
    assert definition.requires_confirmation is False
    with pytest.raises(AgentToolArgumentsError):
        registry.validate_arguments("search_knowledge_base", {"query": "", "top_k": 99})

    service = RagService(
        KeywordEmbeddingClient(),
        ChromaVectorStore(tmp_path / "missing", "missing"),
        knowledge_base_dir=str(tmp_path),
    )
    executors = AgentToolExecutorRegistry([SearchKnowledgeBaseTool(service)], registry)
    context = AgentToolContext(
        current_user=User(
            id=1,
            username="viewer",
            password_hash="not-used",
            role=UserRole.VIEWER,
            is_active=True,
        )
    )

    with pytest.raises(AgentToolExecutionError, match="尚未初始化"):
        asyncio.run(
            executors.execute(
                "search_knowledge_base",
                {"query": "冷链要求"},
                context,
            )
        )
