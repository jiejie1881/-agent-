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
from app.rag.exceptions import (
    KnowledgeBaseConfigurationError,
    KnowledgeBaseNotReadyError,
)
from app.rag.rag_service import RagService
from app.rag.schemas import KnowledgeChunk, KnowledgeSection
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


def test_cosine_score_is_similarity_not_distance(tmp_path: Path) -> None:
    store = ChromaVectorStore(tmp_path / 'scores', 'score_direction')
    chunks = [KnowledgeChunk(content=str(i), source='rules.md', document_name='rules',
        document_type='dispatch_rule', section='test', chunk_index=i) for i in range(3)]
    store.rebuild(chunks, [[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]])
    results = store.search([1.0, 0.0], top_k=3)
    assert results[0].chunk_index == 0
    assert results[0].score == pytest.approx(1.0)
    assert [item.score for item in results[1:]] == pytest.approx([0.0, 0.0])
    assert all(item.source == 'rules.md' for item in results)


def test_relevance_evaluation_set_has_positive_and_negative_labels() -> None:
    import json
    samples = json.loads((Path(__file__).parent / 'fixtures' / 'rag_relevance_queries.json').read_text(encoding='utf-8'))
    assert len({item['id'] for item in samples}) == len(samples)
    assert sum(item['relevant'] for item in samples) == 6
    assert sum(not item['relevant'] for item in samples) == 4
    for item in samples:
        assert item['query'].strip()
        if item['relevant']:
            assert item['expected_source'] and item['expected_section']


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


def test_retired_transport_index_does_not_return_obsolete_rules(tmp_path: Path) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    source = knowledge / "cold_chain_rules.md"
    source.write_text("# 冷链\n冷冻货物必须进行温控匹配。", encoding="utf-8")
    service = build_service(tmp_path, knowledge)
    service.rebuild()
    assert service.search("冷冻", top_k=1)
    source.write_text("# 当前能力\n分类和温控已停用，需要人工核实特殊要求。", encoding="utf-8")
    assert service.search("冷冻", top_k=1) == []
    assert service.status().ready  # Preserve the index, don't erase unrelated knowledge.
    service.rebuild()
    assert "已停用" in service.search("温控", top_k=1)[0].content


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


def test_hybrid_search_reuses_versioned_chunks_after_restart_and_tool_call(tmp_path: Path) -> None:
    from app.rag.bm25_index import tokenize

    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "dispatch_rules.md").write_text(
        "# 派车方案\n车辆出勤后，调度员检查线路载重并发布派车方案。", encoding="utf-8")
    (knowledge / "exception_handling.md").write_text(
        "# 签收回单\n司机完成配送后上传签收回单，缺失时允许补传。", encoding="utf-8")
    store = ChromaVectorStore(tmp_path / "chroma", "hybrid")
    service = RagService(KeywordEmbeddingClient(), store, knowledge_base_dir=str(knowledge),
                         retrieval_mode="hybrid", chunk_size=200, chunk_overlap=0)
    service.rebuild()
    first = service.search("调度员检查车辆出勤后发布派车方案", top_k=2)
    assert first and any(item.source == "dispatch_rules.md" for item in first)
    dispatch = next(item for item in first if item.source == "dispatch_rules.md")
    assert dispatch.vector_rank and dispatch.bm25_rank
    assert first[0].retrieval_sources == ["vector", "bm25"]
    assert first[0].vector_distance is not None and first[0].score == pytest.approx(
        1 - first[0].vector_distance)
    assert dispatch.rrf_score is not None
    assert dispatch.index_version
    assert "v3" in tokenize("V3 FOUR_METER vehicle_203")
    # A new service instance recovers the manifest and persisted Chroma collection.
    restarted = RagService(KeywordEmbeddingClient(), ChromaVectorStore(tmp_path / "chroma", "hybrid"),
                           knowledge_base_dir=str(knowledge), retrieval_mode="hybrid",
                           chunk_size=200, chunk_overlap=0)
    assert restarted.search("签收回单补传", top_k=2)[0].source == "exception_handling.md"
    context = AgentToolContext(current_user=User(id=1, username="viewer", password_hash="x",
        role=UserRole.VIEWER, is_active=True))
    result = asyncio.run(AgentToolExecutorRegistry(
        [SearchKnowledgeBaseTool(restarted)], AgentToolRegistry()).execute(
            "search_knowledge_base", {"query": "签收回单补传", "top_k": 2}, context))
    assert result.data["results"][0]["retrieval_sources"]
    assert result.data["results"][0]["index_version"]


def test_langgraph_model_tool_call_reaches_real_hybrid_rag_service(tmp_path: Path) -> None:
    from app.agent.agent_service import AgentService
    from app.agent.model_types import AgentModelResponse, AgentToolCall

    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "dispatch_rules.md").write_text(
        "# 发布规则\nAgent 候选由后端确定性校验，调度员人工确认后才能发布。", encoding="utf-8")
    rag = RagService(KeywordEmbeddingClient(), ChromaVectorStore(tmp_path / "chroma", "graph-rag"),
                     knowledge_base_dir=str(knowledge), retrieval_mode="hybrid")
    rag.rebuild()

    class Model:
        def __init__(self):
            self.calls = 0

        async def chat(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return AgentModelResponse(tool_calls=(AgentToolCall(
                    id="rag-call", name="search_knowledge_base",
                    arguments={"query": "调度员如何发布 Agent 派车候选"}),))
            tool_messages = [message for message in messages if message.role.value == "tool"]
            assert len(tool_messages) == 1
            assert "index_version" in tool_messages[0].content
            assert "bm25" in tool_messages[0].content
            return AgentModelResponse(content="候选须经校验并由调度员确认发布。")

    registry = AgentToolRegistry()
    executors = AgentToolExecutorRegistry([SearchKnowledgeBaseTool(rag)], registry)
    model = Model()
    agent = AgentService(model, registry, executors, max_tool_calls=2,
                         checkpoint_path=tmp_path / "graph.sqlite3")
    actor = User(id=1, username="viewer", password_hash="unused", role=UserRole.VIEWER,
                 is_active=True)
    result = asyncio.run(agent.chat("Agent候选如何发布？", AgentToolContext(current_user=actor)))
    assert result.used_tools == ("search_knowledge_base",)
    assert result.tool_calls_count == 1
    assert result.content == "候选须经校验并由调度员确认发布。"


def test_hybrid_rebuild_is_idempotent_and_old_chunks_retire(tmp_path: Path) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    document = knowledge / "manual.txt"
    document.write_text("唯一流程 alpha 的审核步骤。", encoding="utf-8")
    service = RagService(KeywordEmbeddingClient(), ChromaVectorStore(tmp_path / "chroma", "life"),
                         knowledge_base_dir=str(knowledge), retrieval_mode="hybrid")
    service.rebuild()
    previous = service.search("alpha 审核", top_k=1)[0]
    service.rebuild()
    repeated = service.search("alpha 审核", top_k=1)[0]
    assert repeated.chunk_id == previous.chunk_id
    assert repeated.index_version != previous.index_version
    document.unlink()
    (knowledge / "other.txt").write_text("完全不同的配送确认内容。", encoding="utf-8")
    service.rebuild()
    assert all(item.source != "manual.txt" for item in service.search("alpha", top_k=4))


def test_failed_candidate_build_keeps_active_version(tmp_path: Path) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    source = knowledge / "guide.txt"
    source.write_text("当前有效内容 alpha", encoding="utf-8")
    service = RagService(KeywordEmbeddingClient(), ChromaVectorStore(tmp_path / "chroma", "rollback"),
                         knowledge_base_dir=str(knowledge), retrieval_mode="hybrid")
    service.rebuild()
    version = service.search("alpha", top_k=1)[0].index_version
    source.write_text("新版本内容 beta", encoding="utf-8")
    service.embedding_client.embed_documents = lambda texts: (_ for _ in ()).throw(RuntimeError("offline"))
    with pytest.raises(RuntimeError):
        service.rebuild()
    assert service.versions.load()[0]["version"] == version


def test_failed_candidate_validation_keeps_active_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.versioned_index import VersionedIndex

    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    source = knowledge / "guide.txt"
    source.write_text("stable previous alpha", encoding="utf-8")
    service = RagService(KeywordEmbeddingClient(), ChromaVectorStore(tmp_path / "chroma", "validate"),
                         knowledge_base_dir=str(knowledge), retrieval_mode="hybrid")
    service.rebuild()
    version = service.versions.load()[0]["version"]
    source.write_text("candidate data beta", encoding="utf-8")
    monkeypatch.setattr(VersionedIndex, "validate_vector",
                        lambda *args, **kwargs: (_ for _ in ()).throw(KnowledgeBaseNotReadyError("mismatch")))
    with pytest.raises(KnowledgeBaseNotReadyError, match="mismatch"):
        service.rebuild()
    assert service.versions.load()[0]["version"] == version


def test_manifest_checksum_mismatch_fails_closed(tmp_path: Path) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "guide.txt").write_text("dispatch guide", encoding="utf-8")
    service = RagService(KeywordEmbeddingClient(), ChromaVectorStore(tmp_path / "chroma", "checksum"),
                         knowledge_base_dir=str(knowledge), retrieval_mode="hybrid")
    service.rebuild()
    pointer = service.versions.root / "active.json"
    import json
    ref = json.loads(pointer.read_text(encoding="utf-8"))["manifest"]
    path = service.versions.root / ref
    value = json.loads(path.read_text(encoding="utf-8"))
    value["payload"]["chunks"][0]["access_scope"] = "admin"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(KnowledgeBaseNotReadyError, match="版本或权限"):
        service.search("dispatch", top_k=1)


def test_hybrid_degrades_only_when_other_route_and_manifest_are_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.rag.bm25_index import BM25Index

    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "guide.txt").write_text("派车车辆出勤与线路审核规则", encoding="utf-8")
    store = ChromaVectorStore(tmp_path / "chroma", "degrade")
    service = RagService(KeywordEmbeddingClient(), store, knowledge_base_dir=str(knowledge),
                         retrieval_mode="hybrid")
    service.rebuild()
    monkeypatch.setattr(ChromaVectorStore, "search",
                        lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
    lexical = service.search("车辆出勤派车", top_k=2)
    assert lexical and lexical[0].retrieval_sources == ["bm25"]
    assert lexical[0].score is None  # Never invent a vector score for lexical-only results.
    assert service.last_search_stats["degraded"] == ("vector",)

    monkeypatch.undo()
    monkeypatch.setattr(BM25Index, "search", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
    vector = service.search("车辆出勤派车", top_k=2)
    assert vector and vector[0].retrieval_sources == ["vector"]
    assert service.last_search_stats["degraded"] == ("bm25",)
