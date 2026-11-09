"""Shared pre-request budget and input gate for authorized local shadow acceptance."""
import json
from decimal import Decimal

from app.agent.dispatch_workflow import reserve_tokens
from app.agent.exceptions import AgentModelError
from app.agent.langchain_client import LangChainModelClient

CAP = Decimal("0.50")
INPUT_RATE = Decimal(3)
OUTPUT_RATE = Decimal(9)
MAX_CALLS = 9
MAX_TOKENS = 50000
FORBIDDEN_TEXT = ("隔离演示门店", "foundation-driver", "foundation-standby",
                  "anonymous-driver", "湘A00001", "湘A00002", "step95-driver", "湘A95001", "湘A95002")
FORBIDDEN_KEYS = {"resource_records", "password", "password_hash", "api_key",
                  "plate_number", "username", "name", "contact_name", "contact_phone"}


def deny(code):
    raise AgentModelError("Step 9.5 模型调用已安全停止", status_code=503, code=code)


def scan(value):
    if isinstance(value, dict):
        if FORBIDDEN_KEYS.intersection(value):
            deny("ACCEPTANCE_SENSITIVE_INPUT")
        for item in value.values():
            scan(item)
    elif isinstance(value, list):
        for item in value:
            scan(item)


class RecordingBudgetClient:
    def __init__(self, config, ledger, *, max_output_tokens, inner=None):
        self.inner = inner or LangChainModelClient(config, max_output_tokens=max_output_tokens)
        self.ledger = ledger
        self.calls = 0
        self.output_tokens = max_output_tokens
        self.key = config.agent_api_key.get_secret_value() if config.agent_api_key else None
        self.responses = []
        self.input_keys = []

    async def chat(self, messages, tools):
        payload = json.loads(messages[1].content)
        scan(payload)
        if self.key and any(self.key in (message.content or "") for message in messages):
            deny("ACCEPTANCE_SENSITIVE_INPUT")
        if any(text in messages[1].content for text in FORBIDDEN_TEXT):
            deny("ACCEPTANCE_SENSITIVE_INPUT")
        reservation = reserve_tokens(messages, tools, self.output_tokens)
        if self.calls >= 3 or self.ledger["calls"] >= MAX_CALLS:
            deny("ACCEPTANCE_CALL_BUDGET_EXCEEDED")
        if self.ledger["charged_tokens"] + reservation > MAX_TOKENS:
            deny("ACCEPTANCE_TOKEN_BUDGET_EXCEEDED")
        if Decimal(self.ledger["charged_tokens"] + reservation) * OUTPUT_RATE / 1000000 > CAP:
            deny("ACCEPTANCE_COST_BUDGET_EXCEEDED")
        self.input_keys.append({"context": sorted(payload["context"]), "top_level": sorted(payload)})
        self.calls += 1
        self.ledger["calls"] += 1
        self.ledger["charged_tokens"] += reservation
        self.ledger["reserved_tokens"] += reservation
        response = await self.inner.chat(messages, tools)
        usage = response.token_usage
        if usage is None:
            deny("ACCEPTANCE_USAGE_UNKNOWN")
        self.ledger["reported_tokens"] += usage.total_tokens
        self.ledger["estimated_cost"] += (
            usage.input_tokens * INPUT_RATE + usage.output_tokens * OUTPUT_RATE) / Decimal(1000000)
        self.ledger["charged_tokens"] += max(0, usage.total_tokens - reservation)
        if self.ledger["charged_tokens"] > MAX_TOKENS:
            deny("ACCEPTANCE_TOKEN_BUDGET_EXCEEDED")
        if Decimal(self.ledger["charged_tokens"]) * OUTPUT_RATE / 1000000 > CAP:
            deny("ACCEPTANCE_COST_BUDGET_EXCEEDED")
        self.responses.append(response.model_dump(mode="json"))
        return response
