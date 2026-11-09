import asyncio
from datetime import date
from types import SimpleNamespace

import pytest

from app.domain.enums import UserRole
from app.domain.exceptions import PermissionDeniedError
from tests.legacy_support.local_dispatch_demo import LocalDemoRequest, demo_context, run_demo
from tests.test_agent_dispatch_shadow import settings as base_settings, table_contents


def settings(**overrides):
    return base_settings().model_copy(update={
        "local_dispatch_demo_enabled": False, "local_dispatch_demo_real_enabled": False, **overrides})


@pytest.mark.parametrize("scene,inject,code,assigned", [
    ("normal", False, None, 1), ("overweight", False, None, 0),
    ("terrain", False, None, 1), ("terrain", True, "TERRAIN_NOT_ALLOWED", 1),
    ("overweight", True, "OVERLOAD", 0),
])
def test_demo_real_validator_and_zero_database_changes(session, scene, inject, code, assigned):
    before = table_contents(session)
    response = asyncio.run(run_demo(LocalDemoRequest(scene=scene, inject_violation=inject),
        SimpleNamespace(id=1, role=UserRole.ADMIN, is_active=True), settings(local_dispatch_demo_enabled=True)))
    result = response["result"]
    assert result["status"] == "SUCCESS", result
    assert result["validation"]["is_valid"] and result["freshness_checked"]
    assert result["metrics"]["assigned_count"] == assigned
    if code:
        assert result["revision_count"] == 1
        assert code in [v["violation_code"] for v in result["attempts"][0]["validation"]["violations"]]
    if scene == "terrain":
        assert result["candidate"]["trips"][0]["vehicle_id"] == 2
    assert result["token_usage"] is None and table_contents(session) == before


@pytest.mark.parametrize("role,enabled", [(UserRole.VIEWER, True), (UserRole.DRIVER, True), (UserRole.ADMIN, False)])
def test_demo_security_guard(role, enabled):
    with pytest.raises(PermissionDeniedError):
        asyncio.run(run_demo(LocalDemoRequest(scene="normal"), SimpleNamespace(id=1, role=role),
                             settings(local_dispatch_demo_enabled=enabled)))


def test_real_requires_server_flag_before_network():
    with pytest.raises(PermissionDeniedError):
        asyncio.run(run_demo(LocalDemoRequest(scene="normal", mode="real", authorize_external=True),
            SimpleNamespace(id=1, role=UserRole.ADMIN), settings(local_dispatch_demo_enabled=True)))


def test_context_fingerprint_reproducible():
    ctx = demo_context("terrain", date(2026, 11, 10))
    assert ctx.fingerprint() == ctx.snapshot_version
    assert ctx.snapshot_version == demo_context("terrain", date(2026, 11, 10)).snapshot_version
    assert ctx.terrain_permissions == ((2, 1),)


def test_authenticated_api(client, monkeypatch, session):
    from app.core import config
    monkeypatch.setattr(config, "get_settings", lambda: settings(local_dispatch_demo_enabled=True))
    before = table_contents(session)
    response = client.post("/api/v1/agent/dispatch/demo", json={"scene": "terrain", "inject_violation": True})
    assert response.status_code == 404, response.text
    assert before == table_contents(session)
    assert client.get("/api/v1/agent/dispatch/demo/context?scene=terrain").status_code == 404
