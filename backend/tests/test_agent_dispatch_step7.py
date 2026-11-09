"""Offline injected evidence is explicitly separate from natural real-model errors."""
from copy import deepcopy

import pytest

from tests import test_agent_dispatch_foundation as foundation
from tests.fixtures.verify_step7_real_model import (
    correction_observation,
    terrain_alternative,
)
from tests.test_agent_dispatch_shadow import FakeModel
from tests.test_agent_dispatch_step3_scenarios import _scene
from tests.test_agent_dispatch_step5 import guarded_execute


@pytest.fixture
def resources(session):
    return foundation.resources.__wrapped__(session)


def test_injected_terrain_error_uses_legal_alternative(session, resources):
    ctx, outputs, _, _ = terrain_alternative("terrain_alternative", session, resources)
    model = FakeModel(outputs)
    result = guarded_execute(session, model)
    assert result.status == "SUCCESS" and result.validation.is_valid
    assert result.attempts[0].validation.violations[0].violation_code == "TERRAIN_NOT_ALLOWED"
    assert result.candidate.trips[0].vehicle_id == 2
    assert result.candidate.trips[0].driver_id == resources["standby"].id
    assert result.revision_count == 1 and result.snapshot_version == ctx.snapshot_version


def test_injected_missing_demand_is_repaired(session, resources):
    ctx = foundation.context(session)
    good = foundation.candidate(ctx, resources)
    bad = deepcopy(good)
    bad["trips"] = []
    result = guarded_execute(session, FakeModel([bad, good]))
    assert result.status == "SUCCESS" and result.validation.is_valid
    assert any(v.violation_code == "MISSING_DEMAND" for v in result.attempts[0].validation.violations)
    assert result.metrics.assigned_count == 1 and result.revision_count == 1


@pytest.mark.parametrize("name", ["all_assigned", "overweight", "terrain_mismatch"])
def test_minimal_offline_demo_regression(session, resources, name):
    _ctx, outputs, code, counts = _scene(name, session, resources)
    result = guarded_execute(session, FakeModel(outputs))
    assert result.status == "SUCCESS" and result.validation.is_valid
    assert (result.metrics.assigned_count, result.metrics.unassigned_count) == counts[:2]
    if code:
        assert any(v.violation_code == code for v in result.attempts[0].validation.violations)


@pytest.mark.parametrize("violations,final,expected", [
    ([], True, "NOT OBSERVED"),
    ([{"code": "MISSING_DEMAND"}], True, "NOT OBSERVED"),
    ([{"code": "TERRAIN_NOT_ALLOWED"}], True, "PASS"),
    ([{"code": "TERRAIN_NOT_ALLOWED"}], False, "FAIL"),
])
def test_natural_correction_requires_terrain_error(violations, final, expected):
    receipt = {"attempts": [{"violations": violations, "valid": False},
                            {"violations": [], "valid": final}],
               "scenario_acceptance": "PASS" if final else "FAIL"}
    assert correction_observation(receipt) == expected
