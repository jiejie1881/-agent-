import asyncio

import pytest

from app.agent.knowledge_tools import SearchKnowledgeBaseTool
from app.agent.schemas.tool import SearchKnowledgeBaseArgs
from app.agent.tool_execution import AgentToolContext
from app.core.config import Settings
from app.domain.exceptions import BusinessError
from app.rag.evaluation import EvalCase
from app.rag.governed import GovernedRagFacade
from app.services.knowledge_retrieval_service import KnowledgeRetrievalService
from tests.test_knowledge_management import governance as _governance
from tests.test_knowledge_lifecycle import build


@pytest.fixture(name="governance")
def private_governance(session, tmp_path):
    return _governance.__wrapped__(session, tmp_path)


def published(governance):
    jobs, job = build(governance)
    manager, base, actors = governance
    jobs.validate(actors["admin"], job.result_index_id)
    manager.publish(actors["admin"], job.result_index_id, None, 0, True)
    return manager, base, actors


@pytest.mark.parametrize("mode", ["vector", "bm25", "hybrid"])
def test_agent_and_laboratory_share_results_permissions_and_citations(governance, mode):
    manager, base, actors = published(governance)
    config = Settings(_env_file=None, app_environment="test", rag_governance_enabled=True,
        rag_governance_offline_enabled=True, rag_governance_root=str(manager.root),
        rag_governance_default_base_id=base.id, rag_retrieval_mode=mode)
    agent_service = GovernedRagFacade(manager.session, config)
    lab = KnowledgeRetrievalService(manager.session, manager.root, offline=True, default_base_id=base.id, default_strategy=mode)
    expected = lab.search_for_actor(actors["viewer"], "车辆载重", 4)
    tool = SearchKnowledgeBaseTool(agent_service)
    actual = asyncio.run(tool.execute(SearchKnowledgeBaseArgs(query="车辆载重", top_k=4, knowledge_base_id=base.id),
                                      AgentToolContext(current_user=actors["viewer"])))
    assert actual.data["results"] == [x.model_dump() for x in expected]
    assert actual.data["evidence_status"] == "CANDIDATES_UNVERIFIED"
    assert all(x.document_id.startswith(f"kb:{base.id}:") and x.chunk_id and x.index_version for x in expected)


def test_document_delete_takes_effect_on_both_routes_without_rebuilding(governance):
    manager, base, actors = published(governance)
    doc = manager.documents(actors["admin"], base.id)[0]
    manager.delete_document(actors["admin"], doc.id, doc.revision, True)
    service = KnowledgeRetrievalService(manager.session, manager.root, offline=True, default_base_id=base.id)
    for mode in ("vector", "bm25", "hybrid"):
        assert service.search_for_actor(actors["viewer"], "车辆载重", strategy=mode) == []
        assert service.last_candidates == []


def test_permission_revocation_during_search_filters_before_return(governance, monkeypatch):
    manager, base, actors = published(governance)
    service = KnowledgeRetrievalService(manager.session, manager.root, offline=True)
    rag, _, _ = service.prepare(actors["viewer"], base.id, "vector")
    original = rag.embedding_client.embed_query
    doc = manager.documents(actors["admin"], base.id)[0]
    def revoke(text):
        manager.delete_document(actors["admin"], doc.id, doc.revision, True)
        return original(text)
    monkeypatch.setattr(rag.embedding_client, "embed_query", revoke)
    assert rag.search("车辆载重") == []


def test_metric_entry_rejects_duplicates_without_changing_historical_semantics():
    cases = [EvalCase("x", "anonymous", frozenset({"a"}))]
    with pytest.raises(BusinessError, match="重复"):
        KnowledgeRetrievalService.aggregate_unique(cases, {"x": ["a", "a"]}, 4)
    with pytest.raises(BusinessError, match="重复"):
        KnowledgeRetrievalService.aggregate_unique(cases * 2, {"x": ["a"]}, 4)


def test_real_governance_offline_flag_cannot_be_enabled_in_production():
    with pytest.raises(ValueError, match="APP_ENVIRONMENT"):
        Settings(_env_file=None, app_environment="production", rag_governance_offline_enabled=True)
