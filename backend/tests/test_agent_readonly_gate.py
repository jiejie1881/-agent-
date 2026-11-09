"""Default deny contracts; SQLite and substitute models only, no external calls."""
import asyncio
import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.agent.agent_service import AgentService
from app.agent.exceptions import AgentToolNotFoundError
from app.agent.model_types import AgentModelResponse, AgentToolCall
from app.agent.schemas.tool import (
    CANCEL_DISPATCH_PLAN_DEFINITION,
    CancelDispatchPlanArgs,
    MoveDeliveryDemandArgs,
)
from app.agent.tool_execution import AgentToolContext
from app.agent.tool_registry import WRITE_TOOL_DEFINITIONS, AgentToolRegistry
from app.agent.write_tools import CancelDispatchPlanTool, MoveDeliveryDemandTool
from app.api.agent_dependencies import (
    get_agent_pending_action_service,
    get_agent_service,
)
from app.core.config import Settings, get_settings
from app.domain.enums import AgentPendingActionStatus, UserRole
from app.domain.exceptions import PermissionDeniedError
from app.models.agent_pending_action import AgentPendingAction
from app.models.audit_log import AuditLog
from app.models.dispatch_plan import DispatchPlan
from app.services.dispatch_plan_service import DispatchPlanService
from tests.test_agent_phase2 import create_move_action, current_admin
from tests.test_agent_service import FakeExecutorRegistry, FakeModelClient


@pytest.fixture(autouse=True)
def default_readonly(monkeypatch):
    monkeypatch.setattr(get_settings(), 'agent_write_tools_enabled', False)


def counts(session):
    return tuple(session.scalar(select(func.count()).select_from(model))
                 for model in [DispatchPlan, AgentPendingAction, AuditLog])


def test_settings_defaults_readonly_without_signing_key():
    settings = Settings(_env_file=None, database_url='sqlite://',
                        jwt_secret_key=secrets.token_urlsafe(48),
                        app_environment='production', api_docs_enabled=False,
                        sql_echo=False, run_migrations=False, agent_draft_receipt_secret=None)
    assert not settings.agent_write_tools_enabled
    assert settings.agent_draft_receipt_secret is None
    assert not settings.agent_draft_accept_enabled and not settings.agent_plan_publish_enabled


def test_production_app_starts_without_signing_key(tmp_path):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('AGENT_', 'RAG_'))}
    env.update(DATABASE_URL='sqlite+pysqlite:///:memory:', JWT_SECRET_KEY=secrets.token_urlsafe(48),
               APP_ENVIRONMENT='production', API_DOCS_ENABLED='false', SQL_ECHO='false',
               RUN_MIGRATIONS='false', PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    code = """from app.main import app
from app.core.config import get_settings
from fastapi.testclient import TestClient
assert get_settings().agent_draft_receipt_secret is None
assert not get_settings().agent_write_tools_enabled
with TestClient(app) as c:
    assert c.get('/health').status_code == 200
    assert c.get('/docs').status_code == 404
print('PRODUCTION_STARTUP_WITHOUT_SIGNING_KEY_PASS')
"""
    result = subprocess.run([sys.executable, '-c', code], check=False, cwd=tmp_path, env=env,
                            capture_output=True, timeout=45)
    assert result.returncode == 0, result.stderr.decode(errors='replace')


def test_registry_default_is_seven_readonly_tools():
    registry = AgentToolRegistry()
    assert len(registry.to_openai_tools()) == 7
    assert all(d.read_only for d in registry.list_definitions())


@pytest.mark.parametrize('definition', WRITE_TOOL_DEFINITIONS)
def test_explicit_custom_registry_cannot_make_write_visible(definition):
    registry = AgentToolRegistry([definition])
    assert registry.to_openai_tools() == []
    with pytest.raises(AgentToolNotFoundError):
        registry.get(definition.name)


def test_factory_does_not_register_write_executors(session, monkeypatch):
    monkeypatch.setattr('app.api.agent_dependencies.build_rag_service', lambda: object())
    service = get_agent_service(session)
    assert len(service.tool_registry.list_definitions()) == 7
    for definition in WRITE_TOOL_DEFINITIONS:
        with pytest.raises(AgentToolNotFoundError):
            service.executor_registry.get(definition.name)
    pending = get_agent_pending_action_service(session)
    with pytest.raises(PermissionDeniedError):
        asyncio.run(pending.confirm(1, 1, object()))


@pytest.mark.parametrize('definition', WRITE_TOOL_DEFINITIONS)
def test_model_cannot_invent_hidden_write_tool(client, session, definition):
    actor = current_admin(session)
    args = ({'plan_id': 1} if definition.name == 'cancel_dispatch_plan' else
            {'plan_id': 1, 'delivery_demand_id': 1, 'source_order_id': 1, 'target_order_id': 2})
    model = FakeModelClient([AgentModelResponse(tool_calls=(AgentToolCall(
        id='invented', name=definition.name, arguments=args),))])
    executor = FakeExecutorRegistry()
    service = AgentService(model, AgentToolRegistry(), executor)
    before = counts(session)
    with pytest.raises(AgentToolNotFoundError):
        asyncio.run(service.chat('attempt write', AgentToolContext(current_user=actor)))
    assert len(model.calls[0][1]) == 7
    assert executor.calls == [] and counts(session) == before


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('tool_type,args_type,raw', [
    (CancelDispatchPlanTool, CancelDispatchPlanArgs, {'plan_id': 1}),
    (MoveDeliveryDemandTool, MoveDeliveryDemandArgs,
     {'plan_id': 1, 'delivery_demand_id': 1, 'source_order_id': 1, 'target_order_id': 2}),
])
def test_direct_executor_requires_switch_and_persisted_confirmation(
        client, session, monkeypatch, enabled, tool_type, args_type, raw):
    monkeypatch.setattr(get_settings(), 'agent_write_tools_enabled', enabled)
    before = counts(session)
    with pytest.raises(PermissionDeniedError):
        asyncio.run(tool_type(DispatchPlanService(session)).execute(
            args_type.model_validate(raw), AgentToolContext(current_user=current_admin(session))))
    assert counts(session) == before


def test_old_pending_and_http_confirmation_denied_after_disable(client, session, monkeypatch):
    monkeypatch.setattr(get_settings(), 'agent_write_tools_enabled', True)
    pending, actor, conv, _plan, _args, action = create_move_action(client, session)
    before = counts(session)
    monkeypatch.setattr(get_settings(), 'agent_write_tools_enabled', False)
    with pytest.raises(PermissionDeniedError):
        asyncio.run(pending.confirm(conv['id'], action.id, actor))
    response = client.post(f"/api/v1/agent/conversations/{conv['id']}/pending-actions/{action.id}/confirm")
    assert response.status_code == 403
    session.refresh(action)
    assert action.status == AgentPendingActionStatus.PENDING and counts(session) == before


def test_old_checkpoint_cannot_resume_write_after_disable(client, session, tmp_path, monkeypatch):
    from tests.test_langgraph_workflow import pending_graph
    monkeypatch.setattr(get_settings(), 'agent_write_tools_enabled', True)
    service, actor, conv, _, _, action = pending_graph(client, session, tmp_path)
    before = counts(session)
    monkeypatch.setattr(get_settings(), 'agent_write_tools_enabled', False)
    with pytest.raises(PermissionDeniedError):
        asyncio.run(service.resume_action(conv['id'], action.id, actor, 'confirm'))
    assert session.get(AgentPendingAction, action.id).status == AgentPendingActionStatus.PENDING
    assert counts(session) == before


def test_pending_creation_denied_even_with_explicit_write_definition(client, session):
    pending = get_agent_pending_action_service(session)
    before = counts(session)
    with pytest.raises(PermissionDeniedError):
        pending.create(CANCEL_DISPATCH_PLAN_DEFINITION, CancelDispatchPlanArgs(plan_id=1),
                       AgentToolContext(current_user=current_admin(session), conversation_id=1))
    assert counts(session) == before


def test_opt_in_registry_keeps_both_hitl_contracts(monkeypatch):
    monkeypatch.setattr(get_settings(), 'agent_write_tools_enabled', True)
    definitions = AgentToolRegistry().list_definitions()
    assert len(definitions) == 9
    assert all(d.requires_confirmation for d in definitions if not d.read_only)


def test_pending_status_cannot_be_used_as_confirmation(client, session, monkeypatch):
    monkeypatch.setattr(get_settings(), 'agent_write_tools_enabled', True)
    _, actor, conv, _plan, args, action = create_move_action(client, session)
    before = counts(session)
    with pytest.raises(PermissionDeniedError):
        asyncio.run(MoveDeliveryDemandTool(DispatchPlanService(session)).execute(
            MoveDeliveryDemandArgs(**args), AgentToolContext(current_user=actor,
            conversation_id=conv['id'], pending_action_id=action.id)))
    assert counts(session) == before


def test_viewer_cannot_bypass_agent_via_traditional_write_endpoint(client, session):
    from app.services.auth_service import AuthService
    AuthService(session).create_user('readonly-viewer', 'IsolatedViewer123!', UserRole.VIEWER)
    token = client.post('/api/v1/auth/login', json={
        'username': 'readonly-viewer', 'password': 'IsolatedViewer123!'}).json()['access_token']
    before = counts(session)
    response = client.post('/api/v1/dispatch-plans/1/cancel', headers={'Authorization': 'Bearer ' + token})
    assert response.status_code == 403 and counts(session) == before
