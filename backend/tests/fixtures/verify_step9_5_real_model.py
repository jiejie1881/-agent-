"""Authorized Step 9.5 real-model trials against fresh in-memory synthetic SQLite scenes."""
import argparse
import json
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from app.core.config import Settings
from tests.fixtures.verify_step3_real_model import run_scene
from tests.legacy_support.step9_5_budget import (
    CAP, INPUT_RATE, MAX_CALLS, MAX_TOKENS, OUTPUT_RATE, RecordingBudgetClient,
)
from tests.fixtures.verify_step7_real_model import terrain_alternative
from tests.test_agent_dispatch_step3_scenarios import _scene

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorized", action="store_true")
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if not args.authorized:
        parser.error("Explicit current-turn external-send approval required before invocation")
    receipt = args.receipt.resolve()
    root = Path(__file__).resolve().parents[3]
    if not receipt.is_relative_to((root / ".validation-v11" / "step9-5-local").resolve()):
        parser.error("Receipt must stay in the Step 9.5 validation folder")
    config = Settings(_env_file=root / ".env")
    url = urlsplit(config.agent_base_url or "")
    if (config.agent_model != "deepseek-ai/DeepSeek-V4-Flash" or url.scheme != "https"
            or url.hostname != "api.siliconflow.cn" or not config.agent_api_key
            or config.agent_dispatch_shadow_max_cost is None
            or config.agent_dispatch_shadow_max_cost > CAP
            or config.agent_dispatch_shadow_input_price_per_million != INPUT_RATE
            or config.agent_dispatch_shadow_output_price_per_million != OUTPUT_RATE
            or config.agent_dispatch_shadow_cost_currency != "CNY"):
        parser.error("Verified model target, rates or existing per-run cap do not match")
    config = config.model_copy(update={"agent_dispatch_shadow_enabled": True,
        "agent_timeout": 60, "agent_dispatch_shadow_timeout": 120,
        "agent_dispatch_shadow_max_revisions": 2,
        "agent_dispatch_shadow_output_tokens": 1536,
        "agent_dispatch_shadow_token_budget": MAX_TOKENS})
    ledger = {"calls": 0, "charged_tokens": 0, "reserved_tokens": 0,
              "reported_tokens": 0, "estimated_cost": Decimal(0)}
    rows = [{"metadata": {"model": config.agent_model, "target_host": url.hostname,
        "data": "three fresh synthetic in-memory SQLite databases", "scenes": 3,
        "cost_cap_cny": str(CAP), "max_model_calls": MAX_CALLS,
        "max_total_reserved_tokens": MAX_TOKENS, "max_output_tokens_per_call": 1536,
        "http_timeout_seconds": 60, "workflow_timeout_seconds": 120,
        "price_input_cny_per_million": str(INPUT_RATE),
        "price_output_cny_per_million": str(OUTPUT_RATE),
        "actual_provider_bill": "UNKNOWN"}}]
    stopped = False
    for name in ("all_assigned", "overweight", "terrain_alternative"):
        if stopped:
            rows.append({"scene": name, "scenario_acceptance": "NOT RUN", "reason": "prior safety or model block"})
            continue
        clients = []
        def factory(settings, *, max_output_tokens):
            client = RecordingBudgetClient(settings, ledger, max_output_tokens=max_output_tokens)
            clients.append(client)
            return client
        item = run_scene(name, config, model_factory=factory,
                         scene_setup=terrain_alternative if name == "terrain_alternative" else _scene)
        item["raw_model_responses"] = clients[0].responses
        item["sent_field_keys"] = clients[0].input_keys
        rows.append(item)
        stopped = not item["zero_business_write"] or item["status"] == "BLOCKED"
    rows.append({"ledger": ledger,
        "reserved_upper_cny": str(Decimal(ledger["charged_tokens"]) * OUTPUT_RATE / 1000000),
        "overall": "PASS" if all(r.get("scenario_acceptance") == "PASS" for r in rows[1:4]) else "NOT PASS",
        "actual_provider_bill": "UNKNOWN"})
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text("\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in rows) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(receipt), "outcomes": [r.get("scenario_acceptance") for r in rows[1:4]],
        "calls": ledger["calls"], "reserved_upper_cny": rows[-1]["reserved_upper_cny"],
        "overall": rows[-1]["overall"]}, ensure_ascii=False))
    return 0 if rows[-1]["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
