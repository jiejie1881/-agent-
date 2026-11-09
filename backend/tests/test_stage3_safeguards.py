from __future__ import annotations

import math
import subprocess
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.agent.knowledge_tools import SearchKnowledgeBaseTool
from app.agent.schemas.tool import SearchKnowledgeBaseArgs
from app.agent.tool_execution import AgentToolContext
from app.core import business_clock
from app.core.config import Settings
from app.domain.enums import UserRole
from app.models.user import User
from app.rag.rag_service import RagService
from app.rag.reranker import LocalCrossEncoderReranker, rerank_candidates
from app.rag.schemas import KnowledgeSearchResult
from app.rag.vector_store import ChromaVectorStore
from app.services.driver_service import DriverService
from tests.test_rag import KeywordEmbeddingClient
from tests.test_rag_hybrid_safety import chunk


def settings(**kw):
    return Settings(
        _env_file=None, database_url="sqlite://", jwt_secret_key="x" * 40, **kw
    )


@pytest.mark.parametrize(
    "flag", ["agent_draft_accept_enabled", "agent_plan_publish_enabled"]
)
def test_dispatcher_only_requires_signing_secret(flag):
    role_flag = (
        "agent_draft_accept_dispatcher_enabled"
        if "draft" in flag
        else "agent_plan_publish_dispatcher_enabled"
    )
    with pytest.raises(ValidationError, match="SECRET"):
        settings(**{flag: True, role_flag: True})
    assert settings(
        **{flag: True, role_flag: True}, agent_draft_receipt_secret="s" * 40
    )


def test_business_day_crosses_host_utc_midnight_and_driver_uses_it(monkeypatch):
    class Clock:
        @staticmethod
        def now(zone):
            return datetime(2026, 10, 14, 17, tzinfo=UTC).astimezone(zone)

    monkeypatch.setattr(business_clock, "datetime", Clock)
    monkeypatch.setattr(
        business_clock,
        "get_settings",
        lambda: SimpleNamespace(business_timezone="Asia/Shanghai"),
    )
    assert business_clock.business_today() == date(2026, 10, 15)
    monkeypatch.setattr(
        "app.services.driver_service.business_today", lambda: date(2026, 10, 15)
    )
    service = DriverService.__new__(DriverService)
    service.repository = Mock()
    service.repository.list_for_driver.return_value = ([], 0)
    assert service.today(SimpleNamespace(id=12)) == []
    service.repository.list_for_driver.assert_called_once_with(
        12, delivery_date=date(2026, 10, 15)
    )


def test_production_fail_closed_and_docs_can_be_disabled():
    with pytest.raises(ValidationError, match="Production requires"):
        settings(app_environment="production")
    assert settings(
        app_environment="production", api_docs_enabled=False, run_migrations=False
    )
    with pytest.raises(ValidationError):
        settings(rag_reranker_enabled=True)


def test_production_app_exposes_health_but_not_api_documentation():
    import json
    import os
    import sys

    env = os.environ.copy()
    env.update(APP_ENVIRONMENT="production", API_DOCS_ENABLED="false", RUN_MIGRATIONS="false",
               SQL_ECHO="false", DATABASE_URL="sqlite+pysqlite:///:memory:", JWT_SECRET_KEY="x" * 40)
    source = "from fastapi.testclient import TestClient; from app.main import app; import json; c=TestClient(app); print(json.dumps({p:c.get(p).status_code for p in ['/health','/docs','/redoc','/openapi.json']}))"
    result = subprocess.run([sys.executable, "-c", source], env=env, capture_output=True,
                            encoding="utf-8", timeout=20, check=True)
    assert json.loads(result.stdout) == {"/health": 200, "/docs": 404, "/redoc": 404, "/openapi.json": 404}


@pytest.mark.parametrize("scores", [[math.nan, 1], [math.inf, 1], [1]])
def test_invalid_reranker_scores_rejected(scores):
    model = SimpleNamespace(score=lambda *args: scores)
    with pytest.raises(ValueError):
        rerank_candidates(
            "q",
            [
                KnowledgeSearchResult(**chunk("a").model_dump()),
                KnowledgeSearchResult(**chunk("b").model_dump()),
            ],
            model,
        )


def test_reranker_preserves_provenance_and_deterministic_ties():
    items = [
        KnowledgeSearchResult(**chunk(k).model_dump(exclude={"index_version"}), rrf_score=0.1, index_version="v")
        for k in ["b", "a"]
    ]
    ranked = rerank_candidates("q", items, SimpleNamespace(score=lambda *args: [1, 1]))
    assert [x.chunk_id for x in ranked] == ["a", "b"]
    assert all(x.index_version == "v" and x.rrf_score == 0.1 for x in ranked)


def test_local_adapter_timeout_and_offline_env(tmp_path, monkeypatch):
    def run(*args, **kw):
        assert (
            kw["env"]["HF_HUB_OFFLINE"] == "1"
            and kw["env"]["TRANSFORMERS_OFFLINE"] == "1"
        )
        assert kw["timeout"] == 0.1
        raise subprocess.TimeoutExpired("worker", 0.1)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(subprocess.TimeoutExpired):
        LocalCrossEncoderReranker(str(tmp_path), timeout=0.1).score("q", ["x"])


def test_actual_subprocess_timeout_is_bounded(tmp_path):
    # Test the same subprocess.run timeout primitive, without model downloads.
    import sys
    import time

    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run(
            [sys.executable, "-c", "import time;time.sleep(5)"],
            timeout=0.1,
            capture_output=True,
            check=False,
        )
    assert time.monotonic() - start < 3


def test_reranker_failure_falls_back_and_tool_does_not_claim_answerability(tmp_path):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "manual.txt").write_text(
        "配送任务签收回单处理说明。", encoding="utf-8"
    )

    class Bad:
        def score(self, *args):
            raise RuntimeError("secret must not leak")

    rag = RagService(
        KeywordEmbeddingClient(),
        ChromaVectorStore(tmp_path / "chroma", "stage3"),
        knowledge_base_dir=str(knowledge),
        retrieval_mode="hybrid",
        reranker=Bad(),
    )
    rag.rebuild()
    assert (
        rag.search("签收回单")
        and rag.last_search_stats["reranker_status"] == "FALLBACK"
    )
    tool = SearchKnowledgeBaseTool(rag)
    actor = User(
        id=1, username="viewer", role=UserRole.VIEWER, password_hash="x", is_active=True
    )
    result = tool._execute(
        SearchKnowledgeBaseArgs(query="签收回单"), AgentToolContext(current_user=actor)
    )
    assert (
        result["evidence_status"] == "CANDIDATES_UNVERIFIED"
        and result["answerability"] == "NOT_EVALUATED"
    )
    empty = tool._execute(
        SearchKnowledgeBaseArgs(query="q", document_type="none"),
        AgentToolContext(current_user=actor),
    )
    assert empty["evidence_status"] == "NO_EVIDENCE"
