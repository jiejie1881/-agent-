"""Approval consistency and committed-result recovery on owned test data.

No providers or external databases are used. SQLite validates application
semantics here; row-lock/CAS behaviour still requires isolated MySQL evidence.
"""
import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import event, select

from app.agent.schemas.tool import CancelDispatchPlanArgs
from app.agent.tool_execution import AgentToolContext
from app.domain.enums import AgentPendingActionStatus, DispatchPlanStatus, UserRole
from app.domain.exceptions import AgentPendingActionError, NotFoundError, PermissionDeniedError
from app.models.agent_pending_action import AgentPendingAction
from app.models.audit_log import AuditLog
from app.models.dispatch_plan import DispatchOrderDetail, DispatchPlan
from app.services.auth_service import AuthService
from tests.test_agent_phase2 import build_pending_service, create_move_action, current_admin, service_status
from tests.test_dispatch_plan_adjustment import generate_adjustable_plan


@pytest.fixture(autouse=True)
def enable_owned_write_contract(monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "agent_write_tools_enabled", True)


def movement_audits(session):
    return session.scalars(select(AuditLog).where(AuditLog.action == "DISPATCH_DEMAND_MOVED")).all()


@pytest.mark.parametrize("change", ["version", "status", "quantity", "arguments", "display", "summary"])
def test_changed_approval_stops_before_any_business_write(client, session, change):
    service, actor, conversation, plan, arguments, action = create_move_action(client, session)
    model = session.get(DispatchPlan, plan["id"])
    if change == "version":
        model.version += 1
    elif change == "status":
        model.status = DispatchPlanStatus.PUBLISHED
    elif change == "quantity":
        detail = session.scalar(select(DispatchOrderDetail).where(
            DispatchOrderDetail.delivery_demand_id == arguments["delivery_demand_id"]
        ))
        detail.quantity += Decimal("1")
    elif change == "arguments":
        action.arguments = {**action.arguments, "source_order_id": arguments["target_order_id"]}
    elif change == "display":
        action.display_data = {**action.display_data, "quantity": "999"}
    else:
        action.summary = "不同的审批描述"
    session.commit()

    with pytest.raises(AgentPendingActionError) as error:
        asyncio.run(service.confirm(conversation["id"], action.id, actor))

    assert error.value.code == "AGENT_ACTION_SNAPSHOT_CHANGED"
    assert service_status(session, action.id) == AgentPendingActionStatus.FAILED
    detail = session.scalar(select(DispatchOrderDetail).where(
        DispatchOrderDetail.delivery_demand_id == arguments["delivery_demand_id"]
    ))
    assert detail.dispatch_order_id == arguments["source_order_id"]
    assert movement_audits(session) == []


def test_unchanged_snapshot_executes_original_service_once(client, session):
    service, actor, conversation, _plan, arguments, action = create_move_action(client, session)
    executed, result = asyncio.run(service.confirm(conversation["id"], action.id, actor))
    assert executed.status == AgentPendingActionStatus.EXECUTED
    assert result.data["status"] == "executed"
    detail = session.scalar(select(DispatchOrderDetail).where(
        DispatchOrderDetail.delivery_demand_id == arguments["delivery_demand_id"]
    ))
    assert detail.dispatch_order_id == arguments["target_order_id"]
    assert len(movement_audits(session)) == 1
    with pytest.raises(AgentPendingActionError) as duplicate:
        asyncio.run(service.confirm(conversation["id"], action.id, actor))
    assert duplicate.value.code == "AGENT_ACTION_ALREADY_EXECUTED"


@pytest.mark.parametrize("change_snapshot", [False, True])
def test_cancel_plan_snapshot_and_committed_receipt(client, session, change_snapshot):
    generated, plan, *_ = generate_adjustable_plan(client, [100, 100])
    conversation = client.post("/api/v1/agent/conversations").json()
    service, registry, _ = build_pending_service(session)
    actor = current_admin(session)
    action = service.create(registry.get("cancel_dispatch_plan"),
                            CancelDispatchPlanArgs(plan_id=generated["plan_id"]),
                            AgentToolContext(current_user=actor, conversation_id=conversation["id"]))
    session.commit()
    if change_snapshot:
        session.get(DispatchPlan, plan["id"]).version += 1
        session.commit()
        with pytest.raises(AgentPendingActionError) as error:
            asyncio.run(service.confirm(conversation["id"], action.id, actor))
        assert error.value.code == "AGENT_ACTION_SNAPSHOT_CHANGED"
        assert session.get(DispatchPlan, plan["id"]).status == DispatchPlanStatus.DRAFT
        assert session.scalars(select(AuditLog).where(AuditLog.action == "DISPATCH_PLAN_CANCELLED")).all() == []
    else:
        asyncio.run(service.confirm(conversation["id"], action.id, actor))
        receipt = service.recover_execution(conversation["id"], action.id, actor)
        assert receipt.tool_name == "cancel_dispatch_plan"
        assert receipt.data["plan_id"] == plan["id"]
        assert receipt.data["recovery_verified"] is True
        assert session.get(DispatchPlan, plan["id"]).status == DispatchPlanStatus.CANCELLED
        assert len(session.scalars(select(AuditLog).where(AuditLog.action == "DISPATCH_PLAN_CANCELLED")).all()) == 1


@pytest.mark.parametrize("change", ["quantity", "assignment"])
def test_cancel_fingerprint_detects_changes_that_preserve_version_and_member_count(client, session, change):
    service, actor, conversation, plan, arguments, _move_action = create_move_action(client, session)
    registry = service.executor_registry.definition_registry
    action = service.create(registry.get("cancel_dispatch_plan"),
                            CancelDispatchPlanArgs(plan_id=plan["id"]),
                            AgentToolContext(current_user=actor, conversation_id=conversation["id"]))
    session.commit()
    approved = dict(action.display_data)
    detail = session.scalar(select(DispatchOrderDetail).where(
        DispatchOrderDetail.delivery_demand_id == arguments["delivery_demand_id"]
    ))
    if change == "quantity":
        detail.quantity += Decimal("1")
    else:
        detail.dispatch_order_id = arguments["target_order_id"]
    session.commit()
    session.expire_all()
    current = service._preview("cancel_dispatch_plan", action.arguments)[1]
    assert {key: value for key, value in current.items() if key != "approval_fingerprint"} == {
        key: value for key, value in approved.items() if key != "approval_fingerprint"
    }, "This regression must preserve the previously checked display fields"
    assert current["approval_fingerprint"] != approved["approval_fingerprint"]
    with pytest.raises(AgentPendingActionError) as error:
        asyncio.run(service.confirm(conversation["id"], action.id, actor))
    assert error.value.code == "AGENT_ACTION_SNAPSHOT_CHANGED"
    assert service_status(session, action.id) == AgentPendingActionStatus.FAILED
    assert session.get(DispatchPlan, plan["id"]).status == DispatchPlanStatus.DRAFT
    assert session.scalars(select(AuditLog).where(AuditLog.action == "DISPATCH_PLAN_CANCELLED")).all() == []


def test_legacy_approval_without_fingerprint_requires_new_consent(client, session):
    service, actor, conversation, _plan, _arguments, action = create_move_action(client, session)
    action.display_data = {key: value for key, value in action.display_data.items()
                           if key != "approval_fingerprint"}
    session.commit()
    with pytest.raises(AgentPendingActionError) as error:
        asyncio.run(service.confirm(conversation["id"], action.id, actor))
    assert error.value.code == "AGENT_ACTION_SNAPSHOT_CHANGED"
    assert service_status(session, action.id) == AgentPendingActionStatus.FAILED
    assert movement_audits(session) == []


def execute_movement(client, session):
    values = create_move_action(client, session)
    service, actor, conversation, _plan, _arguments, action = values
    asyncio.run(service.confirm(conversation["id"], action.id, actor))
    return values


def test_recovery_returns_verified_commit_receipt_and_issues_only_reads(client, session):
    service, actor, conversation, plan, _arguments, action = execute_movement(client, session)
    statements = []

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lstrip().split(None, 1)[0].upper())

    event.listen(session.bind, "before_cursor_execute", record)
    try:
        first = service.recover_execution(conversation["id"], action.id, actor)
        second = service.recover_execution(conversation["id"], action.id, actor)
    finally:
        event.remove(session.bind, "before_cursor_execute", record)
    assert first == second
    assert first.data["status"] == "executed"
    assert first.data["recovery_verified"] is True
    assert first.data["plan_id"] == plan["id"]
    assert first.data["action_id"] == action.id
    assert first.data["audit_id"] == movement_audits(session)[0].id
    assert first.data["result_reconstructed"] == "commit_receipt_only"
    assert first.data["original_result_available"] is False
    assert "version" not in first.data  # The original full result was not persisted.
    assert statements and set(statements) == {"SELECT"}
    assert len(movement_audits(session)) == 1


def test_recovery_of_pending_action_is_not_execution(client, session):
    service, actor, conversation, _plan, _arguments, action = create_move_action(client, session)
    with pytest.raises(AgentPendingActionError) as error:
        service.recover_execution(conversation["id"], action.id, actor)
    assert error.value.code == "AGENT_ACTION_NOT_EXECUTED"
    assert service_status(session, action.id) == AgentPendingActionStatus.PENDING
    assert movement_audits(session) == []


def test_committed_receipt_is_readable_after_write_tools_are_disabled(client, session, monkeypatch):
    from app.agent.tool_registry import AgentToolRegistry
    from app.core.config import get_settings
    service, actor, conversation, _plan, _arguments, action = execute_movement(client, session)
    monkeypatch.setattr(get_settings(), "agent_write_tools_enabled", False)
    service.executor_registry.definition_registry = AgentToolRegistry()
    assert "move_delivery_demand" not in {
        item.name for item in service.executor_registry.definition_registry.list_definitions()
    }
    assert service.recover_execution(conversation["id"], action.id, actor).data["recovery_verified"] is True
    assert len(movement_audits(session)) == 1


@pytest.mark.parametrize("change", ["missing", "wrong-plan", "duplicate", "missing-timestamp"])
def test_recovery_requires_unambiguous_matching_committed_audit(client, session, change):
    service, actor, conversation, _plan, _arguments, action = execute_movement(client, session)
    audit = movement_audits(session)[0]
    if change == "missing":
        session.delete(audit)
    elif change == "wrong-plan":
        audit.changes = {**audit.changes, "plan_id": -1}
    elif change == "missing-timestamp":
        action.executed_at = None
    else:
        session.add(AuditLog(user_id=audit.user_id, username=audit.username,
                            action=audit.action, object_type=audit.object_type,
                            object_id=audit.object_id, changes=dict(audit.changes)))
    session.commit()
    with pytest.raises(AgentPendingActionError) as error:
        service.recover_execution(conversation["id"], action.id, actor)
    assert error.value.code == "AGENT_ACTION_RECOVERY_UNVERIFIED"
    assert service_status(session, action.id) == AgentPendingActionStatus.EXECUTED


def test_recovery_preserves_owner_and_live_permission_checks(client, session):
    service, actor, conversation, _plan, _arguments, action = execute_movement(client, session)
    other = AuthService(session).create_user("recover-other", "OtherPass123!", UserRole.ADMIN)
    with pytest.raises(NotFoundError):
        service.recover_execution(conversation["id"], action.id, other)
    actor.role = UserRole.VIEWER
    session.commit()
    with pytest.raises(PermissionDeniedError):
        service.recover_execution(conversation["id"], action.id, actor)
    assert len(movement_audits(session)) == 1


def test_lost_response_after_commit_recovers_without_replaying_write(client, session, monkeypatch):
    service, actor, conversation, _plan, arguments, action = create_move_action(client, session)
    failure = RuntimeError("synthetic response lost after commit")
    native_refresh = session.refresh

    def fail_refresh(instance, *args, **kwargs):
        if isinstance(instance, AgentPendingAction) and instance.status == AgentPendingActionStatus.EXECUTED:
            raise failure
        return native_refresh(instance, *args, **kwargs)

    monkeypatch.setattr(session, "refresh", fail_refresh)
    with pytest.raises(RuntimeError) as error:
        asyncio.run(service.confirm(conversation["id"], action.id, actor))
    assert error.value is failure
    result = service.recover_execution(conversation["id"], action.id, actor)
    assert result.data["recovery_verified"] is True
    assert len(movement_audits(session)) == 1
    detail = session.scalar(select(DispatchOrderDetail).where(
        DispatchOrderDetail.delivery_demand_id == arguments["delivery_demand_id"]
    ))
    assert detail.dispatch_order_id == arguments["target_order_id"]


def test_failure_record_cannot_replace_original_tool_exception(client, session, monkeypatch):
    service, actor, conversation, _plan, _arguments, action = create_move_action(client, session)
    original = RuntimeError("synthetic original tool failure")

    async def fail_tool(*_args, **_kwargs):
        raise original

    def fail_record(*_args, **_kwargs):
        raise OSError("synthetic failure record unavailable")

    monkeypatch.setattr(service.executor_registry, "execute", fail_tool)
    monkeypatch.setattr(service, "_mark_failed", fail_record)
    with pytest.raises(RuntimeError) as error:
        asyncio.run(service.confirm(conversation["id"], action.id, actor))
    assert error.value is original
    assert any("failure state not persisted: OSError" in note for note in original.__notes__)
    assert movement_audits(session) == []
    assert service_status(session, action.id) == AgentPendingActionStatus.PENDING


def test_rollback_failure_is_attached_without_masking_original(client, session, monkeypatch):
    service, actor, conversation, _plan, _arguments, action = create_move_action(client, session)
    original = RuntimeError("synthetic original failure")

    def fail_rollback():
        raise OSError("synthetic rollback unavailable")

    with monkeypatch.context() as local:
        local.setattr(session, "rollback", fail_rollback)
        service._preserve_execution_failure(original, action.id, conversation["id"], actor.id)
    assert original.__notes__ == ["Agent rollback not verified: OSError"]
    assert service_status(session, action.id) == AgentPendingActionStatus.PENDING
    assert movement_audits(session) == []
