"""Bounded diagnostics and accounting; all providers and databases are offline."""
import asyncio
import json
from decimal import Decimal

import httpx
import pytest
from app.agent.exceptions import AgentModelTimeoutError
from app.agent.langchain_client import LangChainModelClient
from app.agent.model_types import (
    AgentMessageRole,
    AgentModelMessage,
    AgentModelResponse,
    AgentTokenUsage,
)
from pydantic import SecretStr

from tests import test_agent_dispatch_foundation as foundation
from tests.test_agent_dispatch_shadow import (
    FakeModel,
    candidate,
    context,
    execute,
    settings,
    table_contents,
)


@pytest.fixture
def resources(session):
    return foundation.resources.__wrapped__(session)


def test_node_and_call_diagnostics_are_per_request(session, resources):
    data = candidate(context(session), resources)
    first = execute(session, FakeModel([data]))
    second = execute(session, FakeModel([data]))
    assert len(first.model_calls) == len(second.model_calls) == 1
    assert [t.node for t in first.node_timings] == [
        "load_dispatch_context", "prepare_dispatch_generation", "generate_dispatch_candidate",
        "validate_dispatch_candidate", "build_shadow_result",
    ]
    assert all(t.elapsed_ms >= 0 and t.status == "OK" for t in first.node_timings)
    assert first.model_calls[0].status == "OK"


def test_token_budget_prevents_first_external_call(session, resources):
    model = FakeModel([candidate(context(session), resources)])
    result = execute(session, model, config=settings(agent_dispatch_shadow_token_budget=1000))
    assert result.reason_code == "TOKEN_BUDGET_EXCEEDED"
    assert not model.calls and result.generation_count == 0 and not result.model_calls


def test_token_reservation_prevents_second_call_when_usage_unknown(session, resources):
    bad = candidate(context(session), resources)
    bad["trips"][0]["route_id"] = 999
    measured = execute(session, FakeModel([bad]), config=settings(agent_dispatch_shadow_max_revisions=0))
    model = FakeModel([bad])
    before = table_contents(session)
    result = execute(session, model, config=settings(
        agent_dispatch_shadow_token_budget=measured.reserved_tokens))
    assert result.status == "BLOCKED" and result.reason_code == "TOKEN_BUDGET_EXCEEDED"
    assert len(model.calls) == len(result.model_calls) == 1
    assert result.token_usage is None and result.token_usage_status == "UNKNOWN"
    assert not result.validation.is_valid and table_contents(session) == before


@pytest.mark.parametrize("rates,code", [
    ({}, "COST_BUDGET_UNCONFIGURED"),
    ({"agent_dispatch_shadow_input_price_per_million": Decimal(1),
      "agent_dispatch_shadow_output_price_per_million": Decimal(2),
      "agent_dispatch_shadow_cost_currency": "TEST_UNIT"}, "COST_BUDGET_EXCEEDED"),
])
def test_money_budget_fails_closed_before_request(session, resources, rates, code):
    model = FakeModel([candidate(context(session), resources)])
    result = execute(session, model, config=settings(agent_dispatch_shadow_max_cost=Decimal("0.000000001"), **rates))
    assert result.status == "BLOCKED" and result.reason_code == code and not model.calls


def test_provider_usage_and_configured_cost_are_reported(session, resources):
    data = candidate(context(session), resources)
    response = AgentModelResponse(content=json.dumps(data, default=str),
        token_usage=AgentTokenUsage(input_tokens=10, output_tokens=5, total_tokens=15))
    result = execute(session, FakeModel([response]), config=settings(
        agent_dispatch_shadow_input_price_per_million=Decimal(1),
        agent_dispatch_shadow_output_price_per_million=Decimal(2),
        agent_dispatch_shadow_cost_currency="TEST_UNIT"))
    assert result.status == "SUCCESS" and result.token_usage.total_tokens == 15
    assert result.token_usage_status == "PROVIDER_REPORTED"
    assert result.estimated_cost == Decimal("0.00002") and result.cost_status == "ESTIMATED"


def test_partial_usage_does_not_claim_complete_accounting(session, resources):
    data = candidate(context(session), resources)
    bad = candidate(context(session), resources, candidate_id="bad")
    bad["trips"][0]["route_id"] = 999
    good = AgentModelResponse(content=json.dumps(data, default=str),
        token_usage=AgentTokenUsage(input_tokens=20, output_tokens=10, total_tokens=30))
    result = execute(session, FakeModel([bad, good]))
    assert result.status == "SUCCESS" and result.revision_count == 1
    assert result.token_usage_status == "PARTIAL" and result.token_usage.total_tokens == 30
    assert result.cost_status == "UNKNOWN" and result.estimated_cost is None


@pytest.mark.parametrize("budget,code", [(50000, "TOKEN_BUDGET_EXCEEDED"), (500000, "COST_BUDGET_EXCEEDED")])
def test_provider_usage_above_reservation_cannot_mark_success(session, resources, budget, code):
    data = candidate(context(session), resources)
    reply = AgentModelResponse(content=json.dumps(data, default=str),
        token_usage=AgentTokenUsage(input_tokens=99999, output_tokens=1, total_tokens=100000))
    before = table_contents(session)
    result = execute(session, FakeModel([reply]), config=settings(
        agent_dispatch_shadow_token_budget=budget,
        agent_dispatch_shadow_max_cost=Decimal("0.05"),
        agent_dispatch_shadow_input_price_per_million=Decimal(1),
        agent_dispatch_shadow_output_price_per_million=Decimal(1),
        agent_dispatch_shadow_cost_currency="TEST_UNIT"))
    assert result.status == "BLOCKED" and result.reason_code == code
    assert table_contents(session) == before


def test_timeout_has_phase_one_call_no_validation_or_retry(session, resources):
    before = table_contents(session)
    result = execute(session, FakeModel([AgentModelTimeoutError(phase="READ")]))
    assert result.reason_code == "AGENT_MODEL_TIMEOUT" and result.validation_count == 0
    assert result.revision_count == 0 and len(result.model_calls) == 1
    assert result.model_calls[0].timeout_phase == "READ"
    assert table_contents(session) == before


def test_workflow_deadline_preserves_cancelled_call_evidence(session, resources):
    ctx = context(session)
    async def slow():
        await asyncio.sleep(1)
        return AgentModelResponse(content="{}")
    result = execute(session, FakeModel([slow]), loader=lambda day: ctx,
        config=settings(agent_dispatch_shadow_timeout=0.05))
    assert result.reason_code == "SHADOW_TIMEOUT"
    assert result.model_calls[0].status == "CANCELLED"
    assert any(t.node == "generate_dispatch_candidate" and t.status == "CANCELLED" for t in result.node_timings)


def provider_config():
    return settings().model_copy(update={
        "agent_provider": "openai-compatible", "agent_model": "offline",
        "agent_base_url": "http://offline.test/v1", "agent_api_key": SecretStr("offline-unusable-placeholder"),
    })


@pytest.mark.parametrize("usage,expected", [
    ({"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}, 120),
    ({"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 121}, None),
    (None, None),
])
def test_langchain_provider_usage_does_not_invent_counts(usage, expected):
    def handler(request):
        body = {"id": "offline", "object": "chat.completion", "created": 0, "model": "offline",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "{}"}}]}
        if usage is not None:
            body["usage"] = usage
        return httpx.Response(200, json=body)
    client = LangChainModelClient(provider_config(), httpx.MockTransport(handler), max_output_tokens=256)
    response = asyncio.run(client.chat([AgentModelMessage(role=AgentMessageRole.USER, content="anonymous")]))
    assert (response.token_usage.total_tokens if response.token_usage else None) == expected


def test_sdk_timeout_is_classified_without_provider_secrets():
    def handler(request):
        raise httpx.ReadTimeout("secret provider URL or key", request=request)
    client = LangChainModelClient(provider_config(), httpx.MockTransport(handler))
    with pytest.raises(AgentModelTimeoutError) as caught:
        asyncio.run(client.chat([AgentModelMessage(role=AgentMessageRole.USER, content="anonymous")]))
    assert caught.value.timeout_phase == "READ"
    assert "secret" not in str(caught.value)
