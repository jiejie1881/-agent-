"""Synthetic Step3 consistency and explanation contracts; no production index."""

from pathlib import Path

import pytest

from app.rag.exceptions import KnowledgeBaseNotReadyError
from app.rag.fusion import reciprocal_rank_fusion
from app.rag.schemas import KnowledgeSearchResult
from tests.test_rag_hybrid_safety import chunk, service


@pytest.mark.parametrize("field,value", [
    ("document_id", "different.txt"),
    ("document_name", "different"),
    ("document_type", "different"),
    ("section", "different"),
    ("chunk_index", 99),
])
def test_fusion_rejects_same_id_with_different_document_identity(field, value):
    original = chunk("a")
    vector = KnowledgeSearchResult(**original.model_dump(), score=.8)
    with pytest.raises(KnowledgeBaseNotReadyError):
        reciprocal_rank_fusion([vector], [(original.model_copy(update={field: value}), 1)], version="v")


@pytest.mark.parametrize("route", ["vector", "bm25"])
def test_fusion_rejects_explicit_foreign_version(route):
    original = chunk("a").model_copy(update={"index_version": "old"})
    vectors = [KnowledgeSearchResult(**original.model_dump(), score=.8)] if route == "vector" else []
    lexical = [(original, 1)] if route == "bm25" else []
    with pytest.raises(KnowledgeBaseNotReadyError):
        reciprocal_rank_fusion(vectors, lexical, version="new")


@pytest.mark.parametrize("route", ["vector", "bm25"])
def test_fusion_rejects_conflicting_duplicate_before_deduplication(route):
    original = chunk("a")
    changed = original.model_copy(update={"document_id": "different.txt"})
    vectors = [KnowledgeSearchResult(**c.model_dump(), score=.8) for c in (original, changed)] if route == "vector" else []
    lexical = [(c, 1) for c in (original, changed)] if route == "bm25" else []
    with pytest.raises(KnowledgeBaseNotReadyError):
        reciprocal_rank_fusion(vectors, lexical, version="v")


def test_fusion_explains_rank_and_preserves_raw_scores():
    a, b = chunk("a"), chunk("b")
    vectors = [KnowledgeSearchResult(**b.model_dump(), score=.1)]
    rows = reciprocal_rank_fusion(vectors, [(a, 1000), (b, -1)], version="v", constant=10)
    assert [x.chunk_id for x in rows] == ["b", "a"]
    assert [x.fusion_rank for x in rows] == [1, 2]
    assert rows[0].rrf_score == pytest.approx(1 / 11 + 1 / 12)
    assert rows[0].bm25_score == -1 and rows[0].score == .1
    assert rows[1].score is None


@pytest.mark.parametrize("mode", ["vector", "bm25", "hybrid"])
def test_same_interface_exposes_final_rank_for_each_strategy(tmp_path, mode):
    rag = service(tmp_path)
    rag.rebuild()
    rag.retrieval_mode = mode
    rows = rag.search("车辆出勤派车", top_k=2)
    assert rows
    assert [x.final_rank for x in rows] == list(range(1, len(rows) + 1))
    assert all(x.fusion_rank >= 1 for x in rows)
    assert len({x.index_version for x in rows}) == 1
    assert all(x.access_scope == "public" for x in rows)


def test_rebuild_removes_deleted_document_from_both_channels(tmp_path):
    rag = service(tmp_path)
    extra = Path(rag.knowledge_base_dir) / "removed.txt"
    extra.write_text("车辆出勤派车方案 删除测试", encoding="utf-8")
    rag.rebuild()
    old = rag.last_built_version
    old_chunks = rag.versions.load()[1]
    assert any(c.source == "removed.txt" for c in old_chunks)
    extra.unlink()
    rag.rebuild()
    assert rag.last_built_version != old
    assert (rag.versions.root / (old + ".json")).is_file()
    for mode in ("vector", "bm25", "hybrid"):
        rag.retrieval_mode = mode
        assert all(x.source != "removed.txt" for x in rag.search("车辆出勤派车方案 删除测试"))
    assert all(c.source != "removed.txt" for c in rag.versions.load()[1])


def test_final_rank_is_assigned_after_optional_reranking(tmp_path):
    rag = service(tmp_path)
    (Path(rag.knowledge_base_dir) / "second.txt").write_text("车辆出勤派车与回单规则。", encoding="utf-8")
    rag.rebuild()
    baseline = rag.search("车辆出勤派车", top_k=10)
    assert len(baseline) > 1
    positions = {x.content: i for i, x in enumerate(baseline)}

    class ReverseReranker:
        def score(self, query, documents):
            return [positions[text] for text in documents]

    rag.reranker = ReverseReranker()
    rows = rag.search("车辆出勤派车", top_k=10)
    assert [x.chunk_id for x in rows] == [x.chunk_id for x in reversed(baseline)]
    assert [x.final_rank for x in rows] == list(range(1, len(rows) + 1))
    assert [x.fusion_rank for x in rows] == list(reversed(range(1, len(rows) + 1)))


@pytest.mark.parametrize("identifier", ["V2", "BIG_VAN", "SMALL_VAN", "STORE-001", "VEH-028"])
def test_exact_identifiers_retrieve_correct_synthetic_document(tmp_path, identifier):
    from app.rag.evaluation import DeterministicHashEmbedding

    rag = service(tmp_path)
    # Identifier-only documents collapse to identical vectors in the keyword
    # fixture. Use the existing token-sensitive offline stand-in for this test.
    rag.embedding_client = DeterministicHashEmbedding()
    for number, value in enumerate(["V2", "BIG_VAN", "SMALL_VAN", "STORE-001", "VEH-028"]):
        (Path(rag.knowledge_base_dir) / f"code-{number}.txt").write_text(
            f"匿名合成编号 {value}，仅用于检索测试。", encoding="utf-8")
    rag.rebuild()
    for mode in ("bm25", "hybrid"):
        rag.retrieval_mode = mode
        result = rag.search(identifier, top_k=1)
        assert result and identifier in result[0].content
        assert result[0].bm25_rank == 1


def test_legacy_vector_result_exposes_final_and_source_rank():
    from types import SimpleNamespace
    from app.rag.rag_service import RagService

    original = chunk("a")
    result = KnowledgeSearchResult(**original.model_dump(), score=.5)
    rag = RagService(SimpleNamespace(embed_query=lambda q: [.1, .2]),
                     SimpleNamespace(persist_directory=Path("not-opened"), collection_name="synthetic",
                                     search=lambda *args: [result]), knowledge_base_dir="not-opened")
    rag.versions = SimpleNamespace(load=lambda: None)
    actual = rag.search("车辆出勤")
    assert actual[0].vector_rank == actual[0].final_rank == 1
    assert actual[0].retrieval_sources == ["vector"]
    assert actual[0].fusion_rank is None
