import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.agent.agent_service import AgentService
from app.agent.model_client import AgentModelClient, ToolDefinition
from app.agent.model_types import AgentModelMessage, AgentModelResponse, AgentToolCall
from app.agent.schemas.tool import CancelDispatchPlanArgs, MoveDeliveryDemandArgs
from app.agent.tool_execution import AgentToolContext, AgentToolExecutorRegistry
from app.agent.tool_registry import AgentToolRegistry
from app.agent.write_tools import build_write_tool_executors
from app.domain.enums import AgentPendingActionStatus, UserRole
from app.domain.exceptions import (
    AgentPendingActionError,
    DispatchAdjustmentValidationError,
    NotFoundError,
    PermissionDeniedError,
)
from app.models.audit_log import AuditLog
from app.models.user import User
from app.services.agent_pending_action_service import AgentPendingActionService
from app.services.auth_service import AuthService
from app.services.dispatch_plan_service import DispatchPlanService
from tests.test_dispatch_plan_adjustment import generate_adjustable_plan


@pytest.fixture(autouse=True)
def opt_in_existing_write_contracts(monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "agent_write_tools_enabled", True)


class WriteCallModel(AgentModelClient):
    def __init__(self, arguments: dict[str, int]) -> None:
        self.responses = [
            AgentModelResponse(
                tool_calls=(AgentToolCall(id="write-1", name="move_delivery_demand", arguments=arguments),)
            ),
            AgentModelResponse(content="该调整尚未执行，请在确认卡片中确认。"),
        ]

    async def chat(
        self,
        messages: Sequence[AgentModelMessage],
        tools: Sequence[ToolDefinition] | None = None,
    ) -> AgentModelResponse:
        return self.responses.pop(0)


def current_admin(session) -> User:
    return session.scalar(select(User).where(User.username == "test-admin"))


def build_pending_service(session):
    registry = AgentToolRegistry()
    dispatch_service = DispatchPlanService(session)
    executors = AgentToolExecutorRegistry(
        build_write_tool_executors(dispatch_service), registry
    )
    return AgentPendingActionService(session, executors, 15), registry, executors


def move_arguments(plan):
    source = next(order for order in plan["orders"] if len(order["details"]) == 2)
    target = next(order for order in plan["orders"] if order["id"] != source["id"])
    return {
        "plan_id": plan["id"],
        "delivery_demand_id": source["details"][0]["delivery_demand_id"],
        "source_order_id": source["id"],
        "target_order_id": target["id"],
    }


def create_move_action(client, session):
    _, plan, *_ = generate_adjustable_plan(client, [100, 100, 50, 50])
    conversation = client.post("/api/v1/agent/conversations").json()
    service, registry, _ = build_pending_service(session)
    user = current_admin(session)
    args = move_arguments(plan)
    action = service.create(
        registry.get("move_delivery_demand"),
        MoveDeliveryDemandArgs.model_validate(args),
        AgentToolContext(current_user=user, conversation_id=conversation["id"]),
    )
    session.commit()
    return service, user, conversation, plan, args, action


def test_model_write_call_creates_pending_action_without_mutating_plan(client, session):
    _, plan, *_ = generate_adjustable_plan(client, [100, 100, 50, 50])
    conversation = client.post("/api/v1/agent/conversations").json()
    pending_service, registry, executors = build_pending_service(session)
    args = move_arguments(plan)
    service = AgentService(
        WriteCallModel(args),
        registry,
        executors,
        pending_action_service=pending_service,
    )

    result = asyncio.run(
        service.chat(
            "移动这个需求",
            AgentToolContext(current_user=current_admin(session), conversation_id=conversation["id"]),
        )
    )

    assert len(result.pending_actions) == 1
    assert result.pending_actions[0].status == AgentPendingActionStatus.PENDING
    unchanged = client.get(f"/api/v1/dispatch-plans/{plan['id']}").json()
    assert move_arguments(unchanged) == args


def test_confirm_executes_once_and_writes_agent_audit(client, session):
    service, user, conversation, plan, args, action = create_move_action(client, session)

    executed, result = asyncio.run(service.confirm(conversation["id"], action.id, user))

    assert executed.status == AgentPendingActionStatus.EXECUTED
    assert result.data["status"] == "executed"
    updated = client.get(f"/api/v1/dispatch-plans/{plan['id']}").json()
    target = next(order for order in updated["orders"] if order["id"] == args["target_order_id"])
    assert args["delivery_demand_id"] in {item["delivery_demand_id"] for item in target["details"]}
    audit = session.scalar(
        select(AuditLog).where(AuditLog.action == "DISPATCH_DEMAND_MOVED").order_by(AuditLog.id.desc())
    )
    assert audit.changes["source"] == "agent"
    assert audit.changes["tool_name"] == "move_delivery_demand"
    assert audit.changes["pending_action_id"] == action.id

    with pytest.raises(AgentPendingActionError) as repeated:
        asyncio.run(service.confirm(conversation["id"], action.id, user))
    assert repeated.value.code == "AGENT_ACTION_ALREADY_EXECUTED"


def test_pending_action_can_be_cancelled_without_business_change(client, session):
    service, user, conversation, plan, args, action = create_move_action(client, session)
    cancelled = service.cancel(conversation["id"], action.id, user)
    assert cancelled.status == AgentPendingActionStatus.CANCELLED
    unchanged = client.get(f"/api/v1/dispatch-plans/{plan['id']}").json()
    source = next(order for order in unchanged["orders"] if order["id"] == args["source_order_id"])
    assert args["delivery_demand_id"] in {item["delivery_demand_id"] for item in source["details"]}

    with pytest.raises(AgentPendingActionError) as cancelled_confirm:
        asyncio.run(service.confirm(conversation["id"], action.id, user))
    assert cancelled_confirm.value.code == "AGENT_ACTION_NOT_PENDING"
    assert session.scalar(
        select(AuditLog).where(AuditLog.action == "DISPATCH_DEMAND_MOVED")
    ) is None


def test_pending_action_enforces_user_conversation_and_expiration(client, session):
    service, user, conversation, plan, args, action = create_move_action(client, session)
    other_conversation = client.post("/api/v1/agent/conversations").json()
    with pytest.raises(NotFoundError):
        service.cancel(other_conversation["id"], action.id, user)
    with pytest.raises(NotFoundError):
        asyncio.run(service.confirm(other_conversation["id"], action.id, user))

    other = AuthService(session).create_user("other-admin", "OtherAdmin123!", UserRole.ADMIN)
    with pytest.raises(NotFoundError):
        service.cancel(conversation["id"], action.id, other)

    action.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    with pytest.raises(AgentPendingActionError) as expired:
        asyncio.run(service.confirm(conversation["id"], action.id, user))
    assert expired.value.code == "AGENT_ACTION_EXPIRED"
    assert service.repository.get(action.id).status == AgentPendingActionStatus.EXPIRED
    unchanged = client.get(f"/api/v1/dispatch-plans/{plan['id']}").json()
    source = next(order for order in unchanged["orders"] if order["id"] == args["source_order_id"])
    assert args["delivery_demand_id"] in {item["delivery_demand_id"] for item in source["details"]}
    assert session.scalar(
        select(AuditLog).where(AuditLog.action == "DISPATCH_DEMAND_MOVED")
    ) is None


def test_viewer_cannot_create_write_pending_action(client, session):
    _, plan, *_ = generate_adjustable_plan(client, [100, 100, 50, 50])
    viewer = AuthService(session).create_user("phase2-viewer", "ViewerPass123!", UserRole.VIEWER)
    from app.models.agent_conversation import AgentConversation

    conversation = AgentConversation(user_id=viewer.id, title="viewer")
    session.add(conversation)
    session.commit()
    service, registry, _ = build_pending_service(session)
    with pytest.raises(PermissionDeniedError):
        service.create(
            registry.get("move_delivery_demand"),
            MoveDeliveryDemandArgs.model_validate(move_arguments(plan)),
            AgentToolContext(current_user=viewer, conversation_id=conversation.id),
        )


def test_permission_is_checked_again_when_confirming(client, session):
    service, user, conversation, _, _, action = create_move_action(client, session)
    user.role = UserRole.VIEWER
    session.commit()

    with pytest.raises(PermissionDeniedError):
        asyncio.run(service.confirm(conversation["id"], action.id, user))

    assert service.repository.get(action.id).status == AgentPendingActionStatus.PENDING


def test_cancel_dispatch_plan_requires_confirmation_and_is_audited(client, session):
    generated, plan, *_ = generate_adjustable_plan(client, [100, 100])
    conversation = client.post("/api/v1/agent/conversations").json()
    service, registry, _ = build_pending_service(session)
    user = current_admin(session)
    action = service.create(
        registry.get("cancel_dispatch_plan"),
        CancelDispatchPlanArgs(plan_id=generated["plan_id"]),
        AgentToolContext(current_user=user, conversation_id=conversation["id"]),
    )
    session.commit()
    assert client.get(f"/api/v1/dispatch-plans/{plan['id']}").json()["status"] == "DRAFT"

    executed, _ = asyncio.run(service.confirm(conversation["id"], action.id, user))

    assert executed.status == AgentPendingActionStatus.EXECUTED
    assert client.get(f"/api/v1/dispatch-plans/{plan['id']}").json()["status"] == "CANCELLED"
    audit = session.scalar(
        select(AuditLog).where(AuditLog.action == "DISPATCH_PLAN_CANCELLED").order_by(AuditLog.id.desc())
    )
    assert audit.changes["source"] == "agent"
    assert audit.changes["pending_action_id"] == action.id


def test_pending_action_api_confirms_and_rejects_second_confirmation(client, session):
    _, _, conversation, _, _, action = create_move_action(client, session)
    url = f"/api/v1/agent/conversations/{conversation['id']}/pending-actions/{action.id}/confirm"

    first = client.post(url)
    second = client.post(url)

    assert first.status_code == 200
    assert first.json()["action"]["status"] == "EXECUTED"
    assert second.status_code == 409
    assert second.json()["code"] == "AGENT_ACTION_ALREADY_EXECUTED"


def test_pending_action_api_isolated_by_user_for_read_confirm_and_cancel(client, session):
    _, _, conversation, _, _, action = create_move_action(client, session)
    AuthService(session).create_user("isolated-admin", "OtherAdmin123!", UserRole.ADMIN)
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "isolated-admin", "password": "OtherAdmin123!"},
    )
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    action_url = f"/api/v1/agent/conversations/{conversation['id']}/pending-actions/{action.id}"

    assert client.get(
        f"/api/v1/agent/conversations/{conversation['id']}", headers=other_headers
    ).status_code == 404
    assert client.post(f"{action_url}/confirm", headers=other_headers).status_code == 404
    assert client.post(f"{action_url}/cancel", headers=other_headers).status_code == 404

    assert service_status(session, action.id) == AgentPendingActionStatus.PENDING


def test_failed_execution_rolls_back_move_audit_and_marks_action_failed(client, session):
    service, user, conversation, plan, args, action = create_move_action(client, session)
    target = next(order for order in plan["orders"] if order["id"] == args["target_order_id"])
    attendances = client.get("/api/v1/vehicle-attendances?date=2026-09-24").json()
    target_attendance = next(
        item for item in attendances if item["vehicle_id"] == target["vehicle"]["id"]
    )
    assert client.patch(
        f"/api/v1/vehicle-attendances/{target_attendance['id']}",
        json={"available": False},
    ).status_code == 200

    with pytest.raises(DispatchAdjustmentValidationError):
        asyncio.run(service.confirm(conversation["id"], action.id, user))

    assert service_status(session, action.id) == AgentPendingActionStatus.FAILED
    unchanged = client.get(f"/api/v1/dispatch-plans/{plan['id']}").json()
    source = next(order for order in unchanged["orders"] if order["id"] == args["source_order_id"])
    target = next(order for order in unchanged["orders"] if order["id"] == args["target_order_id"])
    assert args["delivery_demand_id"] in {item["delivery_demand_id"] for item in source["details"]}
    assert args["delivery_demand_id"] not in {item["delivery_demand_id"] for item in target["details"]}
    assert session.scalar(
        select(AuditLog).where(AuditLog.action == "DISPATCH_DEMAND_MOVED")
    ) is None


def service_status(session, action_id: int) -> AgentPendingActionStatus:
    service, _, _ = build_pending_service(session)
    return service.repository.get(action_id).status
