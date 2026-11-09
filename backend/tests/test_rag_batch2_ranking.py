"""Independent no-ORM tests; Hash vectors are pipeline stand-ins only."""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("batch2_guard_attestation")
from pydantic import ValidationError

from app.rag.bm25_index import tokenize
from app.rag.evaluation import DeterministicHashEmbedding
from app.rag.exceptions import KnowledgeBaseNotReadyError
from app.rag.fusion import reciprocal_rank_fusion
from app.rag.rag_service import RagService
from app.rag.schemas import KnowledgeChunk, KnowledgeSearchResult
from app.rag.vector_store import ChromaVectorStore

IDENTIFIERS = (
    "V1",
    "V2",
    "V10",
    "V02",
    "BIG_VAN",
    "SMALL_VAN",
    "STORE-001",
    "STORE-01",
    "VEH-028",
)


def test_original_keyword_vector_function_collapses_identifier_only_inputs():
    # Compile only this arithmetic method. Do not import its Agent/ORM test module.
    tree = ast.parse(Path(__file__).with_name("test_rag.py").read_text("utf-8"))
    cls = next(
        n
        for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "KeywordEmbeddingClient"
    )
    fn = next(
        n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_vector"
    )
    fn.decorator_list = []
    namespace = {}
    exec(
        compile(
            ast.Module(body=[fn], type_ignores=[]),
            "<original_keyword_arithmetic>",
            "exec",
        ),
        namespace,
    )
    vectors = [
        namespace["_vector"]("匿名合成编号 " + identifier + "，仅用于检索测试。")
        for identifier in IDENTIFIERS
    ]
    assert all(vector == [0.0, 0.0, 0.1] for vector in vectors)
    hash_vectors = DeterministicHashEmbedding().embed_documents(IDENTIFIERS)
    assert len({tuple(row) for row in hash_vectors}) == len(IDENTIFIERS)


@pytest.mark.parametrize("identifier", IDENTIFIERS)
def test_identifier_sensitive_fixture_retrieval_is_stable(tmp_path, identifier):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    for number, value in enumerate(IDENTIFIERS):
        (knowledge / f"code-{number}.txt").write_text(
            f"匿名合成编号 {value}，仅用于检索测试。", encoding="utf-8"
        )
    rag = RagService(
        DeterministicHashEmbedding(),
        ChromaVectorStore(tmp_path / "index", "batch2-codes"),
        knowledge_base_dir=str(knowledge),
        retrieval_mode="hybrid",
    )
    rag.rebuild()
    expected_source = f"code-{IDENTIFIERS.index(identifier)}.txt"
    for mode in ("bm25", "hybrid"):
        rag.retrieval_mode = mode
        first = None
        for _ in range(3):
            hits = rag.search(identifier, top_k=1)
            assert hits and identifier in hits[0].content
            assert hits[0].bm25_rank == 1
            assert hits[0].source == expected_source
            first = first or hits[0].chunk_id
            assert hits[0].chunk_id == first


def test_identifiers_keep_leading_zero_and_normalize_case_without_numeric_coercion():
    for identifier in IDENTIFIERS:
        assert identifier.lower() in tokenize(identifier)
        assert tokenize(identifier) == tokenize(identifier.lower())
    assert "v2" not in tokenize("V02")
    assert "store-001" not in tokenize("STORE-01")


def result(key):
    return KnowledgeSearchResult(
        content="编号重复但稳定的文档",
        source="synthetic.txt",
        document_name="synthetic",
        document_type="system_manual",
        section="规则",
        chunk_index=0,
        chunk_id=key,
        index_version="v",
        score=0.5,
    )


def test_rrf_equal_scores_use_stable_string_ids_not_natural_business_sort():
    # Chunk IDs are opaque strings (normally SHA digests), not vehicle integers.
    a, b = result("v10"), result("v2")
    for _ in range(5):
        rows = reciprocal_rank_fusion([b, a], [(a, 1), (b, 1)], version="v")
        assert [r.chunk_id for r in rows] == ["v10", "v2"]
        assert rows[0].rrf_score == rows[1].rrf_score
    rows = reciprocal_rank_fusion([a, a], [(a, 1), (a, 1)], version="v")
    assert len(rows) == 1 and rows[0].rrf_score == pytest.approx(2 / 61)


@pytest.mark.parametrize("bad", [None, 2, [], {}])
def test_non_string_chunk_identifier_is_not_implicitly_coerced(bad):
    data = result("valid").model_dump()
    data["chunk_id"] = bad
    with pytest.raises(ValidationError):
        KnowledgeChunk.model_validate(data)


def test_missing_identifier_rejected_before_fusion():
    missing = result("").model_copy(update={"chunk_id": ""})
    with pytest.raises(KnowledgeBaseNotReadyError):
        reciprocal_rank_fusion([missing], [], version="v")


def test_same_business_identifier_in_two_sources_retains_both_stable_chunk_ids(
    tmp_path,
):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    for name in ("a", "b"):
        (knowledge / (name + ".txt")).write_text(
            "匿名合成编号 V02 配送规则。", encoding="utf-8"
        )
    rag = RagService(
        DeterministicHashEmbedding(),
        ChromaVectorStore(tmp_path / "index", "duplicates"),
        knowledge_base_dir=str(knowledge),
        retrieval_mode="hybrid",
    )
    rag.rebuild()
    before = rag.search("V02", top_k=2)
    assert len({h.chunk_id for h in before}) == 2
    rag.rebuild()
    assert [h.chunk_id for h in rag.search("V02", top_k=2)] == [
        h.chunk_id for h in before
    ]
