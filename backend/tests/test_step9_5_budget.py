import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.agent.exceptions import AgentModelError
from app.agent.model_types import AgentMessageRole, AgentModelMessage
from tests.legacy_support.step9_5_budget import RecordingBudgetClient


class NeverCalled:
    def __init__(self):
        self.calls = 0

    async def chat(self, messages, tools):
        self.calls += 1
        raise AssertionError("external model call was not blocked")


def client(charged=0):
    inner = NeverCalled()
    ledger = {"calls": 0, "charged_tokens": charged, "reserved_tokens": 0,
              "reported_tokens": 0, "estimated_cost": Decimal(0)}
    config = SimpleNamespace(agent_api_key=SecretStr("test-only-key"))
    return RecordingBudgetClient(config, ledger, max_output_tokens=1536, inner=inner), inner


def messages(context):
    return [AgentModelMessage(role=AgentMessageRole.SYSTEM, content="synthetic-only"),
            AgentModelMessage(role=AgentMessageRole.USER,
                              content=json.dumps({"context": context}))]


@pytest.mark.parametrize("context", [{"stores": [{"name": "private"}]},
                                      {"vehicles": [{"plate_number": "private"}]},
                                      {"resource_records": {}}])
def test_sensitive_field_is_rejected_before_model(context):
    guarded, inner = client()
    with pytest.raises(AgentModelError) as error:
        asyncio.run(guarded.chat(messages(context), []))
    assert error.value.code == "ACCEPTANCE_SENSITIVE_INPUT"
    assert inner.calls == 0


def test_shared_budget_reservation_blocks_before_model():
    guarded, inner = client(charged=49999)
    with pytest.raises(AgentModelError) as error:
        asyncio.run(guarded.chat(messages({"demands": []}), []))
    assert error.value.code == "ACCEPTANCE_TOKEN_BUDGET_EXCEEDED"
    assert inner.calls == 0
