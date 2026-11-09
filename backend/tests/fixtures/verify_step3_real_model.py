"""Opt-in real-model acceptance against anonymous, in-memory shadow scenes only.

Run from backend with python -m tests.fixtures.verify_step3_real_model
--allow-external-anonymous-demo. Never uses the configured
business database, and never prints credentials or the full model prompt.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "anonymous-step3-only-secret-with-at-least-32-characters"

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.agent.dispatch_workflow import ShadowDispatchWorkflow
from app.agent.langchain_client import LangChainModelClient
from app.core.config import Settings
from app.domain.enums import UserRole
from app.infrastructure.database.base import Base
from app.schemas.agent_dispatch import ShadowDispatchRequest
from tests import test_agent_dispatch_foundation as foundation
from tests.test_agent_dispatch_shadow import table_contents
from tests.test_agent_dispatch_step3_scenarios import _scene

SCENES = (
    "all_assigned", "overweight", "leave_without_substitute",
    "confirmed_substitute", "route_mismatch", "terrain_mismatch",
    "period_mismatch", "multi_vehicle_multi_trip", "partial_unassigned",
    "no_full_solution",
)


def summary(name, result, zero_write, expected_counts, select_count):
    attempts = []
    for item in result.attempts:
        candidate = item.candidate
        attempts.append({
            "generation": item.generation,
            "candidate": candidate.model_dump(mode="json") if candidate else None,
            "valid": item.validation.is_valid,
            "violations": [
                {"code": v.violation_code, "message": v.message, "related_ids": v.related_ids}
                for v in item.validation.violations
            ],
        })
    comparison = result.comparison
    acceptance = "BLOCKED" if result.status == "BLOCKED" else (
        "PASS" if result.status == "SUCCESS" and result.validation.is_valid
        and (result.metrics.assigned_count, result.metrics.unassigned_count) == expected_counts
        and zero_write else "FAIL"
    )
    return {
        "scene": name, "status": result.status, "reason_code": result.reason_code,
        "scenario_acceptance": acceptance,
        "expected_assigned_unassigned": list(expected_counts),
        "snapshot_version": result.snapshot_version,
        "freshness_checked": result.freshness_checked,
        "stale_context": result.stale_context,
        "attempts": attempts,
        "generation_count": result.generation_count,
        "revision_count": result.revision_count,
        "validation_count": result.validation_count,
        "metrics": result.metrics.model_dump(mode="json"),
        "comparison": None if comparison is None else {
            "status": comparison.status,
            "metrics": comparison.metrics.model_dump(mode="json") if comparison.metrics else None,
            "validation_valid": comparison.validation.is_valid if comparison.validation else None,
            "elapsed_ms": round(comparison.elapsed_ms, 1),
            "error_code": comparison.error_code,
        },
        "elapsed_ms": round(result.elapsed_ms, 1),
        "token_usage": result.token_usage.model_dump(mode="json") if result.token_usage else None,
        "token_usage_status": result.token_usage_status,
        "node_timings": [item.model_dump(mode="json") for item in result.node_timings],
        "model_calls": [item.model_dump(mode="json") for item in result.model_calls],
        "reserved_tokens": result.reserved_tokens,
        "cost": str(result.estimated_cost) if result.estimated_cost is not None else "UNKNOWN",
        "cost_currency": result.cost_currency,
        "cost_status": result.cost_status,
        "zero_business_write": zero_write,
        "select_statement_count": select_count,
    }


def run_scene(name, settings, *, model_factory=LangChainModelClient, scene_setup=_scene):
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            resources = foundation.resources.__wrapped__(session)
            ctx, _, _, expected_metrics = scene_setup(name, session, resources)
            session.commit()
            before = table_contents(session)
            statements = []

            def capture(conn, cursor, statement, parameters, context, many):
                statements.append(statement)

            workflow = ShadowDispatchWorkflow(
                model_factory(settings, max_output_tokens=settings.agent_dispatch_shadow_output_tokens),
                lambda day: foundation.context(session), settings,
            )
            actor = SimpleNamespace(id=resources["driver"].id,
                                    role=UserRole.ADMIN, is_active=True)
            event.listen(engine, "before_cursor_execute", capture)
            try:
                result = asyncio.run(workflow.run(
                    ShadowDispatchRequest(delivery_date=foundation.DAY, compare_greedy=True), actor,
                ))
            finally:
                event.remove(engine, "before_cursor_execute", capture)
            zero_write = before == table_contents(session) and not (
                session.new or session.dirty or session.deleted) and all(
                    statement.lstrip().upper().startswith("SELECT") for statement in statements)
            receipt = summary(name, result, zero_write, expected_metrics[:2], len(statements))
            receipt["input_summary"] = {
                "date": ctx.delivery_date.isoformat(), "vehicles": len(ctx.vehicles),
                "demands": [{"id": d.id, "kg": str(d.quantity), "period": d.period.value,
                             "store_id": d.store_id} for d in ctx.demands],
                "shifts": [s.model_dump(mode="json") for s in ctx.shifts],
            }
            return receipt
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-external-anonymous-demo", action="store_true")
    parser.add_argument("--scene", choices=SCENES)
    parser.add_argument("--model-timeout", type=float)
    args = parser.parse_args()
    if not args.allow_external_anonymous_demo:
        parser.error("Explicit --allow-external-anonymous-demo is required")
    env_file = Path(__file__).resolve().parents[3] / ".env"
    config = Settings(_env_file=env_file)
    if not all((config.agent_provider, config.agent_model, config.agent_base_url,
                config.agent_api_key and config.agent_api_key.get_secret_value())):
        parser.error("Root .env model configuration is incomplete")
    changes = {"agent_dispatch_shadow_enabled": True}
    if args.model_timeout is not None:
        if not 0 < args.model_timeout <= 90:
            parser.error("--model-timeout must be in (0, 90]")
        changes.update(agent_timeout=args.model_timeout, agent_dispatch_shadow_timeout=120)
    config = config.model_copy(update=changes)
    print(json.dumps({"mode": "anonymous-in-memory-only", "model": config.agent_model,
                      "model_timeout_seconds": config.agent_timeout,
                      "scenes": [args.scene] if args.scene else list(SCENES)}, ensure_ascii=False), flush=True)
    selected = [args.scene] if args.scene else list(SCENES)
    outcomes = []
    for name in selected:
        result = run_scene(name, config)
        outcomes.append(result["scenario_acceptance"])
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if result["reason_code"] in {"AGENT_MODEL_CONFIGURATION_ERROR", "AGENT_MODEL_CONNECTION_ERROR",
                                     "AGENT_MODEL_RESPONSE_ERROR", "AGENT_MODEL_TIMEOUT"}:
            print(json.dumps({"remaining_scenes": selected[len(outcomes):],
                              "reason": "BLOCKED_BY_MODEL_SERVICE"}), flush=True)
            break
    overall = "BLOCKED" if "BLOCKED" in outcomes or len(outcomes) < len(selected) else (
        "FAIL" if "FAIL" in outcomes else "PASS"
    )
    print(json.dumps({"overall": overall, "completed_scenes": len(outcomes)}), flush=True)
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[overall]


if __name__ == "__main__":
    raise SystemExit(main())
