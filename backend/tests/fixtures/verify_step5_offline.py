"""Anonymous terrain receipts using scripted responses only; never external APIs."""
import json

from app.agent.exceptions import AgentModelTimeoutError
from app.agent.model_types import AgentModelResponse
from app.core.config import Settings
from tests.fixtures.verify_step3_real_model import run_scene


class ScriptedModel:
    def __init__(self, mode):
        self.mode, self.calls, self.feedback = mode, 0, []

    async def chat(self, messages, tools):
        self.calls += 1
        payload = json.loads(messages[1].content)
        self.feedback.append({key: payload.get(key) for key in
                              ("terrain_rules", "violation_history", "violations")})
        if self.mode == "third_timeout" and self.calls == 3:
            raise AgentModelTimeoutError(phase="READ")
        ctx = payload["context"]
        vehicle, route, demand = ctx["vehicles"][0], ctx["routes"][0], ctx["demands"][0]
        shift = next(s for s in ctx["shifts"] if s["available"])
        trip = {"vehicle_id": vehicle["id"], "driver_id": shift["driver_id"],
                "route_id": route["id"], "period": demand["period"],
                "trip_no": self.calls if self.mode in {"limit", "third_timeout"} else 1,
                "demand_ids": [demand["id"]]}
        good = self.mode == "no_solution" or (self.mode == "repair" and self.calls > 1)
        raw = {"candidate_id": f"offline-{self.calls}", "delivery_date": ctx["delivery_date"],
               "snapshot_version": ctx["snapshot_version"], "trips": [] if good else [trip],
               "unassigned": [{"demand_id": demand["id"], "explanation": "没有获准进入该地形的车型"}] if good else [],
               "planning_explanation": f"offline scripted response {self.calls}"}
        return AgentModelResponse(content=json.dumps(raw, ensure_ascii=False))


def main():
    settings = Settings(_env_file=None, database_url="sqlite://",
                        jwt_secret_key="offline-only-test-key-at-least-32-chars",
                        agent_dispatch_shadow_enabled=True)
    records = []
    for mode, expected in (("repair", "VALID_CANDIDATE"), ("repeat", "REPEATED_CANDIDATE"),
                           ("no_solution", "VALID_CANDIDATE"), ("limit", "REVISION_LIMIT"),
                           ("third_timeout", "AGENT_MODEL_TIMEOUT")):
        model = ScriptedModel(mode)

        def factory(settings, *, max_output_tokens, scripted=model):
            return scripted

        receipt = run_scene("terrain_mismatch", settings, model_factory=factory)
        receipt.update(case=mode, feedback=model.feedback, mock_calls=model.calls)
        receipt["offline_acceptance"] = "PASS" if receipt["reason_code"] == expected and receipt["zero_business_write"] else "FAIL"
        records.append(receipt)
    print(json.dumps({"environment": "anonymous in-memory SQLite; scripted model only",
                      "external_requests": 0, "provider_tokens": "NOT APPLICABLE", "cost": "NOT APPLICABLE",
                      "overall": "PASS" if all(r["offline_acceptance"] == "PASS" for r in records) else "FAIL",
                      "records": records}, ensure_ascii=False))
    return 0 if all(r["offline_acceptance"] == "PASS" for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
