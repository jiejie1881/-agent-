"""Explicit anonymous-only real acceptance, bounded across the whole suite."""
import argparse
import json
import os
from copy import deepcopy
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "anonymous-step4-only-secret-with-at-least-32-characters"

from app.agent.dispatch_workflow import reserve_tokens
from app.agent.exceptions import AgentModelError
from app.agent.langchain_client import LangChainModelClient
from app.core.config import Settings
from tests.fixtures.verify_step3_real_model import SCENES, run_scene

PROBES = ("repair_probe", "exhaustion_probe", "timeout_probe")


class AcceptanceClient:
    def __init__(self, config, ledger, mode, faults, *, max_output_tokens):
        self.inner = LangChainModelClient(config, max_output_tokens=max_output_tokens)
        self.ledger, self.mode, self.faults = ledger, mode, faults
        self.output_tokens = max_output_tokens
        self.calls = 0

    async def chat(self, messages, tools):
        reservation = reserve_tokens(messages, tools, self.output_tokens)
        if (self.ledger["calls"] >= self.ledger["call_limit"]
                or self.ledger["reserved_tokens"] + reservation > self.ledger["token_limit"]):
            raise AgentModelError("匿名验收总预算耗尽", status_code=503, code="ACCEPTANCE_BUDGET_EXCEEDED")
        self.ledger["calls"] += 1
        self.ledger["reserved_tokens"] += reservation
        self.calls += 1
        response = await self.inner.chat(messages, tools)
        # Fault injection is explicit in the receipt. All model replies remain
        # real; never present the changed candidate as the model's own output.
        inject = self.mode == "exhaustion_probe" or (self.mode == "repair_probe" and self.calls == 1)
        if not inject:
            return response
        try:
            raw = deepcopy(response.tool_calls[0].arguments if response.tool_calls else json.loads(response.content))
        except (ValueError, TypeError, IndexError):
            return response
        original = deepcopy(raw)
        if self.mode == "repair_probe":
            if not isinstance(raw, dict) or not raw.get("trips"):
                return response
            raw["trips"][0]["route_id"] = 999999
        elif isinstance(raw, dict):
            raw["acceptance_only_unknown_field"] = self.calls
        self.faults.append({"generation": self.calls, "mode": self.mode,
                            "original_model_candidate": original, "injected_candidate": raw})
        if response.tool_calls:
            calls = list(response.tool_calls)
            calls[0] = calls[0].model_copy(update={"arguments": raw})
            return response.model_copy(update={"tool_calls": tuple(calls)})
        return response.model_copy(update={"content": json.dumps(raw, ensure_ascii=False)})


def probe_acceptance(mode, receipt, faults):
    if not receipt["zero_business_write"]:
        return "FAIL"
    if mode == "timeout_probe":
        return "PASS" if (receipt["reason_code"] == "AGENT_MODEL_TIMEOUT"
                          and receipt["generation_count"] == 1
                          and receipt["validation_count"] == 0) else "FAIL"
    if receipt["status"] == "BLOCKED":
        return "BLOCKED"
    if mode == "repair_probe":
        attempts = receipt["attempts"]
        return "PASS" if (faults and len(attempts) >= 2 and not attempts[0]["valid"]
                          and attempts[-1]["valid"] and receipt["scenario_acceptance"] == "PASS"
                          and any(v["code"] == "ROUTE_NOT_FOUND" for v in attempts[0]["violations"])) else "FAIL"
    return "PASS" if (len(faults) == 3 and receipt["reason_code"] == "REVISION_LIMIT"
                      and receipt["generation_count"] == 3 and receipt["revision_count"] == 2
                      and all(not a["valid"] for a in receipt["attempts"])) else "FAIL"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-external-anonymous-demo", action="store_true")
    parser.add_argument("--scene", choices=(*SCENES, *PROBES))
    parser.add_argument("--model-timeout", type=float, default=60)
    parser.add_argument("--max-model-calls", type=int, default=24)
    parser.add_argument("--token-budget", type=int, default=400000)
    args = parser.parse_args()
    if not args.allow_external_anonymous_demo:
        parser.error("Explicit anonymous external-call authorization is required")
    if not (0 < args.model_timeout <= 60 and 1 <= args.max_model_calls <= 30
            and 1000 <= args.token_budget <= 500000):
        parser.error("Acceptance limits exceed their hard bounds")
    config = Settings(_env_file=Path(__file__).resolve().parents[3] / ".env")
    config = config.model_copy(update={
        "agent_dispatch_shadow_enabled": True, "agent_timeout": args.model_timeout,
        "agent_dispatch_shadow_timeout": 120, "agent_dispatch_shadow_max_revisions": 2,
        "agent_dispatch_shadow_output_tokens": 1536,
    })
    ledger = {"calls": 0, "reserved_tokens": 0,
              "call_limit": args.max_model_calls, "token_limit": args.token_budget}
    selected = [args.scene] if args.scene else [*SCENES, *PROBES]
    print(json.dumps({"environment": "anonymous-only-in-memory-SQLite", "model": config.agent_model,
                      "timeout": args.model_timeout, "output_tokens_per_call": 1536,
                      "ledger": ledger, "scenes": selected}, ensure_ascii=False), flush=True)
    outcomes = []
    for name in selected:
        faults = []
        scene = "all_assigned" if name in PROBES else name
        scene_config = config.model_copy(update={"agent_timeout": 1.0}) if name == "timeout_probe" else config

        def factory(settings, *, max_output_tokens, mode=name, injected=faults):
            return AcceptanceClient(settings, ledger, mode, injected, max_output_tokens=max_output_tokens)

        receipt = run_scene(scene, scene_config, model_factory=factory)
        receipt["acceptance_case"] = name
        receipt["controlled_faults"] = faults
        if name in PROBES:
            receipt["probe_acceptance"] = probe_acceptance(name, receipt, faults)
        outcomes.append(receipt.get("probe_acceptance", receipt["scenario_acceptance"]))
        print(json.dumps(receipt, ensure_ascii=False), flush=True)
        if receipt["reason_code"] in {"ACCEPTANCE_BUDGET_EXCEEDED", "AGENT_MODEL_CONFIGURATION_ERROR"}:
            print(json.dumps({"remaining_cases": selected[len(outcomes):], "reason": receipt["reason_code"]}), flush=True)
            break
    overall = "BLOCKED" if "BLOCKED" in outcomes or len(outcomes) < len(selected) else "FAIL" if "FAIL" in outcomes else "PASS"
    print(json.dumps({"overall": overall, "ledger": ledger, "completed_cases": len(outcomes)}), flush=True)
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[overall]


if __name__ == "__main__":
    raise SystemExit(main())
