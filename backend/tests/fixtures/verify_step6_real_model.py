"""Three authorized anonymous terrain trials; one shared token/fee ledger."""
import argparse
import json
import os
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "anonymous-step6-only-secret-with-at-least-32-characters"

from app.agent.dispatch_workflow import reserve_tokens
from app.agent.exceptions import AgentModelError
from app.agent.langchain_client import LangChainModelClient
from app.core.config import Settings
from tests.fixtures.verify_step3_real_model import run_scene

INPUT_RATE, OUTPUT_RATE, COST_CAP = Decimal(3), Decimal(9), Decimal("1.10")


def deny(code):
    raise AgentModelError("受控地形验收已安全停止", status_code=503, code=code)


def scan_input(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {"password", "password_hash", "api_key", "token", "authorization",
                               "jwt_secret_key", "receiver_phone", "phone", "contact_phone"}:
                deny("ACCEPTANCE_SENSITIVE_INPUT")
            scan_input(item)
    elif isinstance(value, list):
        for item in value:
            scan_input(item)


class BudgetClient:
    def __init__(self, config, ledger, *, max_output_tokens, inner=None,
                 cost_cap=COST_CAP, max_total_calls=9, max_total_tokens=120000):
        self.inner = inner or LangChainModelClient(config, max_output_tokens=max_output_tokens)
        self.ledger, self.calls, self.output_tokens = ledger, 0, max_output_tokens
        self.cost_cap, self.max_total_calls, self.max_total_tokens = cost_cap, max_total_calls, max_total_tokens
        self.key = config.agent_api_key.get_secret_value() if config.agent_api_key else None

    async def chat(self, messages, tools):
        payload = json.loads(messages[1].content)
        scan_input(payload)
        if self.key and any(self.key in (m.content or "") for m in messages):
            deny("ACCEPTANCE_SENSITIVE_INPUT")
        reservation = reserve_tokens(messages, tools, self.output_tokens)
        if self.calls >= 3 or self.ledger["calls"] >= self.max_total_calls:
            deny("ACCEPTANCE_CALL_BUDGET_EXCEEDED")
        if self.ledger["charged_tokens"] + reservation > self.max_total_tokens:
            deny("ACCEPTANCE_TOKEN_BUDGET_EXCEEDED")
        if Decimal(self.ledger["charged_tokens"] + reservation) * OUTPUT_RATE / 1000000 > self.cost_cap:
            deny("ACCEPTANCE_COST_BUDGET_EXCEEDED")
        self.calls += 1
        self.ledger["calls"] += 1
        self.ledger["charged_tokens"] += reservation
        self.ledger["reserved_tokens"] += reservation
        response = await self.inner.chat(messages, tools)
        usage = response.token_usage
        if usage is None:
            deny("ACCEPTANCE_USAGE_UNKNOWN")
        self.ledger["reported_tokens"] += usage.total_tokens
        self.ledger["estimated_cost"] += (usage.input_tokens * INPUT_RATE + usage.output_tokens * OUTPUT_RATE) / Decimal(1000000)
        self.ledger["charged_tokens"] += max(0, usage.total_tokens - reservation)
        if self.ledger["charged_tokens"] > self.max_total_tokens:
            deny("ACCEPTANCE_TOKEN_BUDGET_EXCEEDED")
        if Decimal(self.ledger["charged_tokens"]) * OUTPUT_RATE / 1000000 > self.cost_cap:
            deny("ACCEPTANCE_COST_BUDGET_EXCEEDED")
        return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-external-anonymous-demo", action="store_true")
    parser.add_argument("--authorize-cny-1-10", action="store_true")
    args = parser.parse_args()
    if not (args.allow_external_anonymous_demo and args.authorize_cny_1_10):
        parser.error("Separate anonymous-data and CNY1.10 fee authorization are required")
    config = Settings(_env_file=Path(__file__).resolve().parents[3] / ".env")
    url = urlsplit(config.agent_base_url or "")
    if (config.agent_model != "deepseek-ai/DeepSeek-V4-Flash" or url.hostname != "api.siliconflow.cn"
            or url.scheme != "https" or not config.agent_api_key):
        parser.error("Verified model/provider configuration does not match")
    config = config.model_copy(update={
        "agent_dispatch_shadow_enabled": True, "agent_timeout": 60,
        "agent_dispatch_shadow_timeout": 120, "agent_dispatch_shadow_max_revisions": 2,
        "agent_dispatch_shadow_output_tokens": 1536, "agent_dispatch_shadow_token_budget": 120000,
        "agent_dispatch_shadow_input_price_per_million": INPUT_RATE,
        "agent_dispatch_shadow_output_price_per_million": OUTPUT_RATE,
        "agent_dispatch_shadow_cost_currency": "CNY", "agent_dispatch_shadow_max_cost": COST_CAP,
    })
    ledger = {"calls": 0, "charged_tokens": 0, "reserved_tokens": 0,
              "reported_tokens": 0, "estimated_cost": Decimal(0)}
    print(json.dumps({"metadata": {"model": config.agent_model, "environment": "anonymous in-memory SQLite",
        "runs": 3, "max_calls_per_run": 3, "max_calls_total": 9, "token_budget": 120000,
        "cost_cap_cny": "1.10", "input_rate_per_million_cny": "3", "output_rate_per_million_cny": "9",
        "http_seconds": 60, "workflow_seconds": 120, "output_token_limit": 1536,
        "pricing_source": "https://docs.siliconflow.cn/docs/release-notes/overview",
        "actual_bill": "UNKNOWN: provider invoice not accessed"}}, ensure_ascii=False), flush=True)
    records, stopped = [], False
    for no in range(1, 4):
        if stopped:
            print(json.dumps({"run": no, "scenario_acceptance": "NOT RUN", "reason": "STOPPED_AFTER_SAFETY_OR_MODEL_FAILURE"}), flush=True)
            continue

        def factory(settings, *, max_output_tokens):
            return BudgetClient(settings, ledger, max_output_tokens=max_output_tokens)

        receipt = run_scene("terrain_mismatch", config, model_factory=factory)
        receipt.update(run=no, actual_bill="UNKNOWN: not retrieved", cost_basis="normal-time noncache upper estimate")
        if ledger["charged_tokens"] > 120000 or not receipt["zero_business_write"]:
            receipt["scenario_acceptance"] = "FAIL"
        print(json.dumps(receipt, ensure_ascii=False), flush=True)
        records.append(receipt)
        stopped = not receipt["zero_business_write"] or receipt["status"] == "BLOCKED"
    overall = "PASS" if len(records) == 3 and all(r["scenario_acceptance"] == "PASS" for r in records) else "BLOCKED" if stopped else "FAIL"
    print(json.dumps({"overall": overall, "ledger": ledger,
                      "estimated_fee_upper_cny": str(Decimal(ledger["charged_tokens"]) * OUTPUT_RATE / 1000000),
                      "completed_runs": len(records)}, default=str), flush=True)
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[overall]


if __name__ == "__main__":
    raise SystemExit(main())
