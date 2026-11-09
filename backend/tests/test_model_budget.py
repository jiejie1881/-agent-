import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.core.model_budget import (BudgetDenied, BudgetPolicy, BudgetedAsyncTransport,
                                   BudgetedSyncTransport, ModelBudget, budget_context, budget_for)
from app.agent.exceptions import AgentModelError
from app.agent.langchain_client import LangChainModelClient
from app.agent.model_client import OpenAICompatibleModelClient
from app.agent.model_types import AgentModelMessage, AgentMessageRole
from app.rag.embedding_client import OpenAICompatibleEmbeddingClient
from app.rag.exceptions import KnowledgeBaseConfigurationError


@pytest.fixture(autouse=True)
def isolated_model_budget():
    # This module tests absent/disabled budgets and provisions its own ledgers.
    with budget_context(None):
        yield


def settings(**kwargs):
    return Settings(_env_file=None, database_url="sqlite+pysqlite:///:memory:",
        jwt_secret_key="synthetic-test-only-secret-at-least-32-chars",
        agent_provider="openai-compatible", agent_model="test-model", agent_api_key="test-key",
        agent_base_url="https://model.example/v1", rag_embedding_provider="openai-compatible",
        rag_embedding_model="test-embedding", rag_embedding_api_key="test-key",
        rag_embedding_base_url="https://model.example/v1", **kwargs)


def make_budget(tmp_path, **kwargs):
    values = dict(max_calls=5, max_micro_cny=100, reserve_micro_cny=10)
    values.update(kwargs)
    budget = ModelBudget(tmp_path / ModelBudget.FILENAME, BudgetPolicy(**values))
    budget.initialize_new(expires_at=time.time() + 3600)
    return budget


def rows(budget):
    with sqlite3.connect(budget.path) as db:
        return db.execute("SELECT operation_id,reserved,status FROM calls ORDER BY operation_id").fetchall()


def test_construction_and_missing_ledger_do_not_create_files(tmp_path):
    budget = ModelBudget(tmp_path / ModelBudget.FILENAME, BudgetPolicy(1, 10, 10))
    with pytest.raises(BudgetDenied, match="预算"):
        budget.reserve("operation-1", "digest", "chat")
    assert not budget.path.exists()
    assert not list(tmp_path.glob("*journal*"))


def test_legacy_real_ledger_name_never_accepted(tmp_path):
    with pytest.raises(BudgetDenied):
        ModelBudget(tmp_path / "yuelu-manual-model-budget.sqlite3", BudgetPolicy(1, 10, 10))


def test_initialize_never_overwrites_or_renews(tmp_path):
    budget = make_budget(tmp_path)
    before = budget.path.read_bytes()
    with pytest.raises(FileExistsError):
        budget.initialize_new(expires_at=time.time() + 7200)
    assert budget.path.read_bytes() == before


@pytest.mark.parametrize("policy", [dict(max_calls=1), dict(max_micro_cny=15)])
def test_call_and_money_limits_prevent_extra_reservation(tmp_path, policy):
    budget = make_budget(tmp_path, **policy)
    budget.reserve("operation-1", "a", "chat")
    budget.finish("operation-1", True)
    with pytest.raises(BudgetDenied) as caught:
        budget.reserve("operation-2", "b", "embedding")
    assert caught.value.reason == "quota_exhausted"
    assert len(rows(budget)) == 1


def test_expired_gate_is_not_refreshed(tmp_path):
    budget = make_budget(tmp_path)
    with sqlite3.connect(budget.path) as db:
        db.execute("UPDATE gate SET expires=1")
    with pytest.raises(BudgetDenied):
        budget.reserve("expired-id", "a", "chat")
    assert rows(budget) == []


def test_unknown_call_keeps_reservation_and_stops_future_calls(tmp_path):
    budget = make_budget(tmp_path)
    budget.reserve("unknown-id", "a", "chat")
    budget.finish("unknown-id", False)
    reopened = ModelBudget(budget.path, budget.policy)
    with pytest.raises(BudgetDenied) as caught:
        reopened.reserve("later-call", "b", "chat")
    assert caught.value.reason == "ledger_stopped_or_expired"
    assert rows(budget) == [("unknown-id", 10, "FAILED_OR_UNKNOWN")]


def test_duplicate_success_and_payload_conflict_never_charge_again(tmp_path):
    budget = make_budget(tmp_path)
    budget.reserve("stable-operation", "a", "chat")
    budget.finish("stable-operation", True)
    for value, reason in [("a", "duplicate_operation"), ("b", "operation_payload_conflict")]:
        with pytest.raises(BudgetDenied) as caught:
            budget.reserve("stable-operation", value, "chat")
        assert caught.value.reason == reason
    assert len(rows(budget)) == 1


def test_atomic_competing_reservations_do_not_oversell(tmp_path):
    budget = make_budget(tmp_path, max_inflight=5, max_calls=2)
    def attempt(index):
        try:
            ModelBudget(budget.path, budget.policy).reserve("operation-" + str(index), "a", "chat")
            return True
        except BudgetDenied:
            return False
    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(attempt, range(8)))
    assert sum(outcomes) == 2
    assert sum(row[1] for row in rows(budget)) == 20


def test_concurrent_same_key_has_exactly_one_reservation(tmp_path):
    budget = make_budget(tmp_path, max_inflight=5)
    def attempt(_):
        try:
            budget.reserve("same-operation", "same-digest", "chat")
            return True
        except BudgetDenied:
            return False
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(attempt, range(8))) == 1
    assert len(rows(budget)) == 1


def test_pending_survives_restart_and_blocks_concurrency(tmp_path):
    budget = make_budget(tmp_path)
    budget.reserve("pending-operation", "a", "chat")
    with pytest.raises(BudgetDenied) as caught:
        ModelBudget(budget.path, budget.policy).reserve("other-operation", "b", "chat")
    assert caught.value.reason == "concurrency_exhausted"


def test_sqlite_budget_lock_and_quota_work_across_processes(tmp_path):
    budget = make_budget(tmp_path, max_calls=2, max_inflight=4)
    code = """import sys,json
sys.path.insert(0,sys.argv[1])
from app.core.model_budget import BudgetPolicy,ModelBudget,BudgetDenied
b=ModelBudget(sys.argv[2],BudgetPolicy(**json.loads(sys.argv[3])))
try:b.reserve(sys.argv[4],'synthetic','chat')
except BudgetDenied:raise SystemExit(3)
"""
    from dataclasses import asdict
    children = [subprocess.Popen([sys.executable, "-I", "-B", "-c", code,
        str(Path(__file__).resolve().parents[1]), str(budget.path), json.dumps(asdict(budget.policy)),
        "process-operation-" + str(index)], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for index in range(4)]
    results = []
    for child in children:
        stdout, stderr = child.communicate(timeout=20)
        assert not stderr, stderr.decode(errors="replace")
        results.append(child.returncode)
    assert sorted(results) == [0, 0, 3, 3]
    assert len(rows(budget)) == 2


@pytest.mark.parametrize("damage", ["corrupt", "missing_gate", "trigger"])
def test_bad_ledger_never_repaired_or_allowed(tmp_path, damage):
    budget = make_budget(tmp_path)
    if damage == "corrupt":
        budget.path.write_bytes(b"synthetic-corrupt-copy")
    else:
        with sqlite3.connect(budget.path) as db:
            if damage == "missing_gate":
                db.execute("DELETE FROM gate")
            else:
                db.execute("CREATE TRIGGER bad AFTER INSERT ON calls BEGIN UPDATE gate SET stopped=0; END")
    before = hashlib.sha256(budget.path.read_bytes()).hexdigest()
    with pytest.raises(BudgetDenied):
        budget.reserve("refused-operation", "a", "chat")
    assert hashlib.sha256(budget.path.read_bytes()).hexdigest() == before


def test_policy_change_cannot_silently_increase_allowance(tmp_path):
    budget = make_budget(tmp_path)
    with pytest.raises(BudgetDenied):
        ModelBudget(budget.path, BudgetPolicy(500, 10000, 1)).reserve("operation-new", "a", "chat")


def test_disabled_budget_blocks_all_three_real_clients_before_mock_upstream():
    calls = []
    def handler(request):
        calls.append(request)
        raise AssertionError("upstream must not run")
    messages = [AgentModelMessage(role=AgentMessageRole.USER, content="test")]
    with budget_context(None):
        for cls in (OpenAICompatibleModelClient, LangChainModelClient):
            with pytest.raises(AgentModelError):
                asyncio.run(cls(settings(), transport=httpx.MockTransport(handler)).chat(messages))
        with pytest.raises(KnowledgeBaseConfigurationError):
            OpenAICompatibleEmbeddingClient(settings(), transport=httpx.MockTransport(handler)).embed_documents(["one", "two"])
    assert calls == []


def test_quota_disabled_style_rewriting_transport_cannot_bypass_guard(tmp_path):
    budget = make_budget(tmp_path)
    class UnsafeRewriter(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            pytest.fail("unreviewed downstream rewriting must never execute")
    with pytest.raises(BudgetDenied) as caught:
        BudgetedAsyncTransport(budget, "https://model.example/v1/chat/completions", "chat", UnsafeRewriter())
    assert caught.value.reason == "unapproved_custom_transport"
    assert rows(budget) == []


def test_configured_real_egress_requires_stable_operation_before_transport_creation(tmp_path, monkeypatch):
    budget = make_budget(tmp_path)
    config = settings(model_budget_enabled=True, model_budget_path=str(budget.path),
                      model_budget_max_calls=5, model_budget_max_micro_cny=100,
                      model_budget_reserve_micro_cny=10)
    def forbidden(*args, **kwargs):
        pytest.fail("No real transport may be constructed without stable operation ID")
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", forbidden)
    monkeypatch.setattr(httpx, "HTTPTransport", forbidden)
    with budget_context(None):
        for cls in (OpenAICompatibleModelClient, LangChainModelClient):
            with pytest.raises(AgentModelError):
                asyncio.run(cls(config).chat([AgentModelMessage(role=AgentMessageRole.USER, content="x")]))
        with pytest.raises(KnowledgeBaseConfigurationError):
            OpenAICompatibleEmbeddingClient(config).embed_query("x")
    assert rows(budget) == []


def test_shared_chat_embedding_quota_and_output_cap(tmp_path):
    budget = make_budget(tmp_path, max_calls=2, max_output_tokens=17)
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        if request.url.path.endswith("embeddings"):
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1, 2]}]})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})
    with budget_context(budget):
        asyncio.run(OpenAICompatibleModelClient(settings(), httpx.MockTransport(handler)).chat(
            [AgentModelMessage(role=AgentMessageRole.USER, content="test")]))
        assert OpenAICompatibleEmbeddingClient(settings(), httpx.MockTransport(handler)).embed_query("one") == [1, 2]
        with pytest.raises(KnowledgeBaseConfigurationError):
            OpenAICompatibleEmbeddingClient(settings(), httpx.MockTransport(handler)).embed_documents(["two"])
    assert calls[0]["max_tokens"] == 17
    assert len(calls) == 2 and len(rows(budget)) == 2


def test_timeout_not_retried_and_unknown_stops_later_call(tmp_path):
    budget = make_budget(tmp_path)
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("synthetic timeout", request=request)
    transport = BudgetedSyncTransport(budget, "https://model.example/v1/embeddings", "embedding", httpx.MockTransport(handler), "stable-timeout")
    request = httpx.Request("POST", transport.endpoint, json={"input": ["synthetic"]})
    with pytest.raises(httpx.ReadTimeout):
        transport.handle_request(request)
    with pytest.raises(BudgetDenied):
        transport.handle_request(request)
    assert len(calls) == 1
    assert rows(budget)[0][2] == "FAILED_OR_UNKNOWN"


def test_async_cancellation_preserves_conservative_charge(tmp_path):
    budget = make_budget(tmp_path)
    async def handler(request):
        raise asyncio.CancelledError()
    transport = BudgetedAsyncTransport(budget, "https://model.example/v1/chat/completions", "chat", httpx.MockTransport(handler))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(transport.handle_async_request(httpx.Request("POST", transport.endpoint, json={"messages": []})))
    assert rows(budget)[0][2] == "FAILED_OR_UNKNOWN"


def test_settlement_failure_does_not_mask_original_timeout(tmp_path, monkeypatch):
    budget = make_budget(tmp_path)
    def broken(*args):
        raise BudgetDenied("synthetic_settlement_error")
    monkeypatch.setattr(budget, "finish", broken)
    def timeout(request):
        raise httpx.ReadTimeout("original timeout")
    transport = BudgetedSyncTransport(budget, "https://model.example/v1/embeddings", "embedding", httpx.MockTransport(timeout))
    with pytest.raises(httpx.ReadTimeout, match="original timeout"):
        transport.handle_request(httpx.Request("POST", transport.endpoint, json={"input": ["x"]}))
    assert rows(budget)[0][2] == "IN_FLIGHT"
    with pytest.raises(BudgetDenied):
        budget.reserve("another-operation", "b", "embedding")


@pytest.mark.parametrize("target,payload", [("https://other.example/v1/embeddings", {"input": ["x"]}),
                                           ("https://model.example/v1/embeddings", {"input": ["x" * 1000]})])
def test_target_and_input_limits_precede_reservation(tmp_path, target, payload):
    budget = make_budget(tmp_path, max_input_bytes=256)
    transport = BudgetedSyncTransport(budget, "https://model.example/v1/embeddings", "embedding", httpx.MockTransport(lambda request: pytest.fail("must not send")))
    with pytest.raises(BudgetDenied):
        transport.handle_request(httpx.Request("POST", target, json=payload))
    assert rows(budget) == []


def test_unconfigured_client_construction_has_no_budget_io(tmp_path):
    with budget_context(None):
        OpenAICompatibleModelClient(settings())
        OpenAICompatibleEmbeddingClient(settings())
        LangChainModelClient(settings())
        with pytest.raises(BudgetDenied):
            budget_for(settings())
    assert list(tmp_path.glob("*")) == []


def test_quality_summary_falls_back_when_budget_disabled():
    from app.services.quality_ai_summary_service import QualityAISummaryService
    report = {"plan_version": 1, "total_score": 100, "grade": "A", "metrics": dict(valid_demand_count=0,
        assigned_demand_count=0, unassigned_count=0, vehicle_count=0, trip_count=0), "dimensions": {},
        "publication_validation": "PASS", "rule_version": "test", "issues": [], "unassigned": []}
    model = OpenAICompatibleModelClient(settings(), httpx.MockTransport(lambda request: pytest.fail("no external call")))
    with budget_context(None):
        result = asyncio.run(QualityAISummaryService(model).summarize(report))
    assert result["mode"] == "RULE_TEMPLATE"


def test_startup_import_never_opens_or_initializes_budget(tmp_path):
    code = """import sys
sys.path.insert(0,sys.argv[1])
from unittest.mock import patch
with patch('sqlite3.connect',side_effect=AssertionError('startup must not connect to SQLite')):
 import app.main
print('normal_app_import_ok_no_sqlite_connect')
"""
    process = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(Path(__file__).resolve().parents[1])],
                             cwd=tmp_path, capture_output=True, timeout=30)
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    assert b"normal_app_import_ok_no_sqlite_connect" in process.stdout
    assert not (tmp_path / ModelBudget.FILENAME).exists()


def test_normal_health_and_master_read_do_not_require_ai(client, tmp_path):
    with budget_context(None):
        assert client.get("/health").status_code == 200
        assert client.get("/health/ready").status_code == 200
        assert client.get("/api/v1/stores").status_code == 200
    assert not (tmp_path / ModelBudget.FILENAME).exists()
