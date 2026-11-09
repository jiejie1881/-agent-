"""Anonymous Step7 acceptance; no forced real-model error and no business writes."""
import argparse
import json
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from app.core.config import Settings
from app.domain.enums import VehicleTypeCode
from app.models.vehicle import Vehicle, VehicleType, VehicleTypeTerrainPermission
from app.models.vehicle_attendance import VehicleAttendance
from tests import test_agent_dispatch_foundation as foundation
from tests.fixtures.verify_step3_real_model import run_scene
from tests.fixtures.verify_step6_real_model import (
    COST_CAP,
    INPUT_RATE,
    OUTPUT_RATE,
    BudgetClient,
)
from tests.test_agent_dispatch_step3_scenarios import _scene


def terrain_alternative(name, session, resources):
    """V1 has no permission; V2's type is explicitly allowed on the same terrain."""
    _scene("terrain_mismatch", session, resources)
    kind = VehicleType(code=VehicleTypeCode.BIG_VAN, name="匿名合法替代车型",
                       min_load=100, max_load=500, is_active=True)
    session.add(kind)
    session.flush()
    vehicle = Vehicle(code="ANON-LEGAL-V2", plate_number="湘A00002",
                      vehicle_type_id=kind.id, driver_user_id=resources["standby"].id,
                      is_active=True)
    session.add(vehicle)
    session.flush()
    session.add_all([
        VehicleTypeTerrainPermission(vehicle_type_id=kind.id, terrain_id=resources["terrain"].id),
        VehicleAttendance(date=foundation.DAY, vehicle_id=vehicle.id, available=True),
    ])
    session.commit()
    ctx = foundation.context(session)
    bad = foundation.candidate(ctx, resources)
    good = foundation.candidate(ctx, resources)
    good["trips"][0].update(vehicle_id=vehicle.id, driver_id=resources["standby"].id)
    return ctx, [bad, good], "TERRAIN_NOT_ALLOWED", (1, 0, 1, 1)


def correction_observation(receipt):
    attempts = receipt.get("attempts", [])
    terrain_indices = [i for i, a in enumerate(attempts) if any(
        v["code"] == "TERRAIN_NOT_ALLOWED" for v in a["violations"])]
    if not terrain_indices:
        return "NOT OBSERVED"
    if receipt["scenario_acceptance"] == "PASS" and any(
        a["valid"] for a in attempts[min(terrain_indices) + 1:]):
        return "PASS"
    return "FAIL"


class RecordingClient(BudgetClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.responses, self.feedback = [], []

    async def chat(self, messages, tools):
        payload = json.loads(messages[1].content)
        self.feedback.append({key: payload[key] for key in ("violations", "violation_history") if key in payload})
        response = await super().chat(messages, tools)
        self.responses.append(response.model_dump(mode="json"))
        return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-external-anonymous-demo", action="store_true")
    parser.add_argument("--authorize-cny-1-10", action="store_true")
    args = parser.parse_args()
    if not (args.allow_external_anonymous_demo and args.authorize_cny_1_10):
        parser.error("Anonymous data and fee authorization required")
    config = Settings(_env_file=Path(__file__).resolve().parents[3] / ".env")
    url = urlsplit(config.agent_base_url or "")
    if config.agent_model != "deepseek-ai/DeepSeek-V4-Flash" or url.hostname != "api.siliconflow.cn" or url.scheme != "https" or not config.agent_api_key:
        parser.error("Verified provider/model configuration does not match")
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
        "injection": False, "max_calls": 9, "token_cap": 120000, "cost_cap_cny": "1.10",
        "http_seconds": 60, "workflow_seconds": 120, "actual_bill": "NOT VERIFIED"}}), flush=True)
    stopped = False
    for name in ("terrain_alternative", "all_assigned", "overweight"):
        if stopped:
            print(json.dumps({"scene": name, "scenario_acceptance": "NOT RUN", "reason": "SAFETY_OR_MODEL_STOP"}), flush=True)
            continue
        clients = []

        def factory(settings, *, max_output_tokens, clients=clients):
            client = RecordingClient(settings, ledger, max_output_tokens=max_output_tokens)
            clients.append(client)
            return client

        receipt = run_scene(name, config, model_factory=factory,
                            scene_setup=terrain_alternative if name == "terrain_alternative" else _scene)
        receipt["raw_model_responses"] = clients[0].responses
        receipt["feedback_sent"] = clients[0].feedback
        receipt["injection"] = False
        if name == "terrain_alternative":
            receipt["natural_terrain_correction"] = correction_observation(receipt)
            receipt["terrain_relation"] = {"forbidden_vehicle_id": 1, "allowed_vehicle_id": 2,
                                           "route_id": 1, "terrain_id": 1}
        print(json.dumps(receipt, ensure_ascii=False), flush=True)
        stopped = not receipt["zero_business_write"] or receipt["status"] == "BLOCKED"
    print(json.dumps({"ledger": ledger, "actual_bill": "NOT VERIFIED"}, default=str), flush=True)


if __name__ == "__main__":
    main()
