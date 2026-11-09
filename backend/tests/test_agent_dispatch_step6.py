"""No networking: shared Step6 request, usage and sensitive-input guards."""
import asyncio
from decimal import Decimal

import pytest
from app.agent.exceptions import AgentModelError
from app.agent.model_types import (
    AgentMessageRole,
    AgentModelMessage,
    AgentModelResponse,
    AgentTokenUsage,
)

from tests.fixtures.verify_step6_real_model import BudgetClient
from tests.test_agent_dispatch_shadow import settings


class Provider:
    def __init__(self, usage):
        self.usage, self.calls = usage, 0

    async def chat(self, messages, tools):
        self.calls += 1
        return AgentModelResponse(content="{}", token_usage=self.usage)


def ledger():
    return {"calls": 0, "charged_tokens": 0, "reserved_tokens": 0, "reported_tokens": 0, "estimated_cost": Decimal(0)}


def invoke(client, payload="{}"):
    return asyncio.run(client.chat([AgentModelMessage(role=AgentMessageRole.SYSTEM, content="offline"),
                                   AgentModelMessage(role=AgentMessageRole.USER, content=payload)], []))


@pytest.mark.parametrize("field,value,code", [("calls", 9, "ACCEPTANCE_CALL_BUDGET_EXCEEDED"),
    ("charged_tokens", 120000, "ACCEPTANCE_TOKEN_BUDGET_EXCEEDED")])
def test_shared_budget_blocks_before_network(field, value, code):
    book, provider = ledger(), Provider(AgentTokenUsage(input_tokens=1, output_tokens=1, total_tokens=2))
    book[field] = value
    client = BudgetClient(settings(), book, max_output_tokens=1536, inner=provider)
    with pytest.raises(AgentModelError) as caught:
        invoke(client)
    assert caught.value.code == code and provider.calls == 0


def test_sensitive_payload_stops_before_network():
    provider = Provider(None)
    with pytest.raises(AgentModelError) as caught:
        invoke(BudgetClient(settings(), ledger(), max_output_tokens=1536, inner=provider), '{"context":{"password":"offline"}}')
    assert caught.value.code == "ACCEPTANCE_SENSITIVE_INPUT" and provider.calls == 0


def test_unknown_usage_stops_after_one_call():
    provider, book = Provider(None), ledger()
    with pytest.raises(AgentModelError) as caught:
        invoke(BudgetClient(settings(), book, max_output_tokens=1536, inner=provider))
    assert caught.value.code == "ACCEPTANCE_USAGE_UNKNOWN" and provider.calls == book["calls"] == 1
    assert book["charged_tokens"] > 0


def test_actual_usage_over_reservation_and_limit_stops():
    provider, book = Provider(AgentTokenUsage(input_tokens=120000, output_tokens=1, total_tokens=120001)), ledger()
    with pytest.raises(AgentModelError) as caught:
        invoke(BudgetClient(settings(), book, max_output_tokens=1536, inner=provider))
    assert caught.value.code == "ACCEPTANCE_TOKEN_BUDGET_EXCEEDED"
    assert book["charged_tokens"] == book["reported_tokens"] == 120001


def test_new_run_clients_share_one_ledger():
    book = ledger()
    usage = AgentTokenUsage(input_tokens=10, output_tokens=5, total_tokens=15)
    for _ in range(3):
        invoke(BudgetClient(settings(), book, max_output_tokens=1536, inner=Provider(usage)))
    assert book["calls"] == 3 and book["reported_tokens"] == 45
    assert book["estimated_cost"] == Decimal("0.000225")
