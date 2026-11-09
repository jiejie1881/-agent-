"""Offline terrain repair acceptance: no external model or business writes."""
import json
from copy import deepcopy

import pytest
from app.agent.dispatch_workflow import ShadowDispatchWorkflow, candidate_signature
from app.agent.exceptions import AgentModelTimeoutError
from app.services.dispatch_candidate_validation_service import (
    DispatchCandidateValidator,
)
from sqlalchemy import event

from tests import test_agent_dispatch_foundation as foundation
from tests.test_agent_dispatch_shadow import (
    FakeModel,
    execute,
    settings,
    table_contents,
)
from tests.test_agent_dispatch_step3_scenarios import _scene


@pytest.fixture
def resources(session):
    return foundation.resources.__wrapped__(session)


def terrain_scene(session, resources):
    ctx, outputs, _, _ = _scene("terrain_mismatch", session, resources)
    return ctx, outputs[0], outputs[1]


def guarded_execute(session, model, **kwargs):
    before, statements = table_contents(session), []
    def capture(conn, cursor, statement, parameters, context, many):
        statements.append(statement)
    event.listen(session.bind, "before_cursor_execute", capture)
    try:
        result = execute(session, model, **kwargs)
    finally:
        event.remove(session.bind, "before_cursor_execute", capture)
    assert table_contents(session) == before
    assert not (session.new or session.dirty or session.deleted)
    assert statements and all(s.lstrip().upper().startswith("SELECT") for s in statements)
    return result


def test_terrain_repair_has_named_rule_and_full_revalidation(session, resources):
    ctx, bad, good = terrain_scene(session, resources)
    model = FakeModel([bad, good])
    result = guarded_execute(session, model)
    assert result.status == "SUCCESS" and result.validation.is_valid
    assert result.validation_count == 2 and result.metrics.unassigned_count == 1
    issue = result.attempts[0].validation.violations[0]
    assert issue.violation_code == "TERRAIN_NOT_ALLOWED"
    assert issue.related_ids["terrain_id"] == resources["terrain"].id
    assert issue.related_ids["vehicle_type_id"] == resources["kind"].id
    assert "普通" in issue.message and "None" not in issue.message
    payload = json.loads(model.calls[1][0][1].content)
    assert payload["terrain_rules"][0]["allowed_vehicle_type_ids"] == []
    assert "terrain_name" not in payload["terrain_rules"][0]
    assert len(payload["violation_history"]) == 1
    assert payload["context"]["snapshot_version"] == ctx.snapshot_version
    assert "不是无限制" in model.calls[0][0][0].content


@pytest.mark.parametrize("change", ["id", "explanation", "trip_order"])
def test_cosmetic_invalid_candidate_stops_without_third_call(session, resources, change):
    _ctx, bad, good = terrain_scene(session, resources)
    repeated = deepcopy(bad)
    if change == "id":
        repeated["candidate_id"] = "cosmetic-different-id"
    elif change == "explanation":
        repeated["planning_explanation"] = "Cosmetic explanation only"
    else:
        repeated["trips"] = list(reversed(repeated["trips"]))
    model = FakeModel([bad, repeated, good])
    result = guarded_execute(session, model)
    assert result.status == "REJECTED" and result.reason_code == "REPEATED_CANDIDATE"
    assert len(model.calls) == result.validation_count == 2
    assert result.validation.violations and not result.validation.is_valid


def test_no_terrain_solution_explicit_unassigned_is_valid(session, resources):
    _ctx, _bad, good = terrain_scene(session, resources)
    result = guarded_execute(session, FakeModel([good]))
    assert result.status == "SUCCESS" and result.metrics.assigned_count == 0
    assert result.metrics.unassigned_count == 1 and result.candidate.trips == ()


def test_incomplete_terrain_label_keeps_ids_and_deny_rule(session, resources):
    ctx, bad, _good = terrain_scene(session, resources)
    ctx = ctx.model_copy(update={"routes": tuple(r.model_copy(update={"terrain_name": None}) for r in ctx.routes)})
    ctx = ctx.model_copy(update={"snapshot_version": ctx.fingerprint()})
    bad["snapshot_version"] = ctx.snapshot_version
    result = DispatchCandidateValidator().validate(bad, ctx)
    assert not result.is_valid and result.violations[0].violation_code == "TERRAIN_NOT_ALLOWED"
    assert "ID=" in result.violations[0].message and "None" not in result.violations[0].message


@pytest.mark.parametrize("feedback", [None, "empty"])
def test_missing_repair_feedback_fails_closed_before_model(session, resources, feedback):
    import asyncio
    ctx, bad, good = terrain_scene(session, resources)
    validation = DispatchCandidateValidator().validate(bad, ctx)
    if feedback == "empty":
        validation = validation.model_copy(update={"violations": ()})
    else:
        validation = None
    model = FakeModel([good])
    workflow = ShadowDispatchWorkflow(model, lambda day: ctx, settings())
    result = asyncio.run(workflow.propose({"context": ctx, "generation_count": 2,
        "revision_count": 1, "validation": validation}, revision=True))
    assert result["reason_code"] == "REPAIR_FEEDBACK_MISSING" and model.calls == []


def test_history_retains_terrain_and_second_violation(session, resources):
    _ctx, bad, good = terrain_scene(session, resources)
    second = deepcopy(bad)
    second["unassigned"] = [{"demand_id": resources["demand"].id, "explanation": "still assigned"}]
    model = FakeModel([bad, second, good])
    result = guarded_execute(session, model)
    assert result.status == "SUCCESS" and result.validation_count == 3
    history = json.loads(model.calls[2][0][1].content)["violation_history"]
    assert [h["generation"] for h in history] == [1, 2]
    assert "ASSIGNED_AND_UNASSIGNED" in json.dumps(history)


def test_third_read_timeout_has_no_fourth_call_or_business_write(session, resources):
    _ctx, bad, good = terrain_scene(session, resources)
    second = deepcopy(bad)
    second["trips"][0]["trip_no"] = 2
    model = FakeModel([bad, second, AgentModelTimeoutError(phase="READ"), good])
    result = guarded_execute(session, model)
    assert result.status == "BLOCKED" and result.reason_code == "AGENT_MODEL_TIMEOUT"
    assert len(model.calls) == 3 and result.revision_count == 2 and result.validation_count == 2
    assert result.model_calls[-1].timeout_phase == "READ"
    assert result.attempts and not result.validation.is_valid
    assert result.metrics.assigned_count == 0


def test_terrain_revision_limit_rejects_distinct_invalid_trips(session, resources):
    _ctx, bad, _good = terrain_scene(session, resources)
    outputs = []
    for no in (1, 2, 3):
        changed = deepcopy(bad)
        changed["trips"][0]["trip_no"] = no
        outputs.append(changed)
    result = guarded_execute(session, FakeModel(outputs))
    assert result.status == "REJECTED" and result.reason_code == "REVISION_LIMIT"
    assert result.validation_count == 3 and result.revision_count == 2
    assert all(not a.validation.is_valid for a in result.attempts)


def test_signature_order_independent_preserves_duplicate_ids():
    base = {"candidate_id": "x", "delivery_date": "2026-11-10", "snapshot_version": "a" * 64,
            "trips": [{"vehicle_id": 1, "driver_id": 1, "route_id": 1, "period": "MORNING",
                       "trip_no": 1, "demand_ids": [1, 2]}], "unassigned": []}
    reordered = deepcopy(base)
    reordered["trips"][0]["demand_ids"] = [2, 1]
    assert candidate_signature(base) == candidate_signature(reordered)
    reordered["trips"][0]["demand_ids"] = [1, 1, 2]
    assert candidate_signature(base) != candidate_signature(reordered)
