from __future__ import annotations

import pytest

from app.rag.bm25_index import BM25Index, tokenize
from app.rag.exceptions import KnowledgeBaseError, KnowledgeBaseNotReadyError
from app.rag.fusion import reciprocal_rank_fusion
from app.rag.rag_service import RagService
from app.rag.schemas import KnowledgeChunk, KnowledgeSearchResult
from app.rag.vector_store import ChromaVectorStore
from tests.test_rag import KeywordEmbeddingClient


def chunk(key, scope="public"):
    return KnowledgeChunk(
        chunk_id=key,
        source=f"{key}.txt",
        document_id=f"{key}.txt",
        content=f"车辆出勤派车方案 {key}",
        document_name=key,
        document_type="system_manual",
        section="规则",
        chunk_index=0,
        access_scope=scope,
    )


@pytest.mark.parametrize(
    "identifier",
    [
        "V1",
        "V2",
        "V3",
        "FOUR_METER",
        "BIG_VAN",
        "SMALL_VAN",
        "STORE-001",
        "/api/v1/dispatch-plans",
    ],
)
def test_identifiers_survive_both_query_and_document_tokenization(identifier):
    assert identifier.lower() in tokenize(identifier)
    assert identifier.lower() in tokenize("车辆编号 " + identifier + " 配送需求")


def test_rrf_formula_missing_routes_and_stable_ties():
    a, b, c = chunk("a"), chunk("b"), chunk("c")
    vector = KnowledgeSearchResult(**a.model_dump(), score=0.8, vector_distance=0.2)
    results = reciprocal_rank_fusion(
        [vector], [(a, 123), (b, 99), (c, 98)], version="v"
    )
    assert results[0].rrf_score == pytest.approx(2 / 61)
    assert results[0].score == 0.8 and results[0].bm25_score == 123
    assert results[1].score is None and results[1].vector_rank is None
    tied = reciprocal_rank_fusion(
        [KnowledgeSearchResult(**b.model_dump(), score=0.5)], [(a, 1)], version="v"
    )
    assert [item.chunk_id for item in tied] == ["a", "b"]
    assert reciprocal_rank_fusion([], [], version="v") == []


def test_rrf_duplicates_never_double_contribute_and_mismatched_metadata_fail():
    a = chunk("a")
    vector = KnowledgeSearchResult(**a.model_dump(), score=0.8)
    assert reciprocal_rank_fusion([vector, vector], [(a, 1), (a, 1)], version="v")[
        0
    ].rrf_score == pytest.approx(2 / 61)
    with pytest.raises(KnowledgeBaseNotReadyError):
        reciprocal_rank_fusion(
            [vector],
            [(a.model_copy(update={"access_scope": "private"}), 1)],
            version="v",
        )


def test_bm25_permission_filter_and_no_overlap():
    a, b = chunk("a"), chunk("b", "private")
    store = BM25Index([a, b])
    assert [c.chunk_id for c, _ in store.search("车辆出勤", {"a"}, 20)] == ["a"]
    assert store.search("zzzz_unknown", {"a"}, 20) == []
    assert BM25Index([]).search("车辆", set(), 20) == []


def service(tmp_path):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "dispatch_rules.md").write_text(
        "# 派车\n车辆出勤载重规则。", encoding="utf-8"
    )
    return RagService(
        KeywordEmbeddingClient(),
        ChromaVectorStore(tmp_path / "chroma", "safe"),
        knowledge_base_dir=str(knowledge),
        retrieval_mode="hybrid",
    )


@pytest.mark.parametrize("top_k", [0, -1, 11])
def test_top_k_bounds_are_rejected(tmp_path, top_k):
    rag = service(tmp_path)
    with pytest.raises(ValueError):
        rag.search("派车", top_k)


def test_build_splits_once_and_changed_source_before_activation_keeps_old(
    tmp_path, monkeypatch
):
    rag = service(tmp_path)
    original = rag.splitter.split
    count = []
    monkeypatch.setattr(
        rag.splitter, "split", lambda sections: (count.append(1), original(sections))[1]
    )
    rag.rebuild()
    assert len(count) == 1
    version = rag.versions.load()[0]["version"]
    validate = rag.versions.validate_vector

    def racing(chunks, store):
        validate(chunks, store)
        (tmp_path / "knowledge" / "dispatch_rules.md").write_text(
            "# 新内容\nChanged", encoding="utf-8"
        )

    monkeypatch.setattr(rag.versions, "validate_vector", racing)
    with pytest.raises(KnowledgeBaseError, match="发生变化"):
        rag.rebuild()
    assert rag.versions.load()[0]["version"] == version


def test_integrity_unavailable_is_safe_error_and_never_unverified_fallback(
    tmp_path, monkeypatch
):
    rag = service(tmp_path)
    rag.rebuild()
    monkeypatch.setattr(
        rag.versions,
        "validate_vector",
        lambda *args: (_ for _ in ()).throw(OSError("sensitive details")),
    )
    with pytest.raises(KnowledgeBaseNotReadyError, match="校验暂不可用") as error:
        rag.search("派车")
    assert "sensitive" not in str(error.value)


def test_two_routes_fail_and_missing_version_and_configuration_change(
    tmp_path, monkeypatch
):
    rag = service(tmp_path)
    with pytest.raises(KnowledgeBaseNotReadyError):
        rag.search("派车")
    rag.rebuild()
    monkeypatch.setattr(
        ChromaVectorStore, "search", lambda *args: (_ for _ in ()).throw(OSError())
    )
    monkeypatch.setattr(
        BM25Index, "search", lambda *args: (_ for _ in ()).throw(OSError())
    )
    with pytest.raises(KnowledgeBaseError):
        rag.search("派车")
    rag.splitter.chunk_size += 1
    with pytest.raises(KnowledgeBaseNotReadyError, match="配置已变化"):
        rag.search("派车")


@pytest.mark.parametrize("mode", ["vector", "bm25", "hybrid"])
def test_retirement_and_type_scope_filters_apply_to_each_route(tmp_path, mode):
    rag = service(tmp_path)
    source = tmp_path / "knowledge" / "cold_chain_rules.md"
    source.write_text("# old\n冷冻必须温控旧规则。", encoding="utf-8")
    rag.rebuild()
    rag.retrieval_mode = mode
    source.write_text("# 新通知\n旧规则已停用。", encoding="utf-8")
    assert all(item.source != "cold_chain_rules.md" for item in rag.search("温控"))
    assert rag.search("派车", document_type="unknown") == []
    assert rag.search("派车", access_scope="private") == []
