from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from app.agent.chat_types import AgentChatResult
from app.agent.exceptions import (
    AgentMaxToolCallsError,
    AgentModelConfigurationError,
    AgentModelConnectionError,
    AgentModelResponseError,
    AgentModelTimeoutError,
    AgentToolArgumentsError,
    AgentToolExecutionError,
    AgentToolNotFoundError,
)
from app.agent.tool_execution import AgentToolContext
from app.api.agent_dependencies import get_agent_service
from app.domain.enums import UserRole
from app.main import app
from app.services.auth_service import AuthService


class FakeAgentService:
    def __init__(
        self,
        result: AgentChatResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result or AgentChatResult(
            content="今天有2辆车出勤。",
            tool_calls_count=1,
            used_tools=("get_vehicle_attendance",),
        )
        self.error = error
        self.calls: list[tuple[str, AgentToolContext]] = []

    async def chat(
        self,
        user_message: str,
        context: AgentToolContext,
    ) -> AgentChatResult:
        self.calls.append((user_message, context))
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def fake_agent_service(client):
    service = FakeAgentService()
    app.dependency_overrides[get_agent_service] = lambda: service
    try:
        yield service
    finally:
        app.dependency_overrides.pop(get_agent_service, None)


def login_headers(client, username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def override_agent_service(service: FakeAgentService) -> None:
    app.dependency_overrides[get_agent_service] = lambda: service


def assert_safe_error(response, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert body["code"] == code
    serialized = response.text.lower()
    assert "traceback" not in serialized
    assert "select " not in serialized
    assert "password_hash" not in serialized


def test_agent_chat_requires_authentication(client, fake_agent_service) -> None:
    response = client.post(
        "/api/v1/agent/chat",
        json={"message": "今天哪些车辆出勤？"},
        headers={"Authorization": ""},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
    assert fake_agent_service.calls == []


@pytest.mark.parametrize(
    "role",
    [UserRole.ADMIN, UserRole.DISPATCHER, UserRole.VIEWER],
)
def test_all_existing_roles_can_use_read_only_agent(
    client, session, fake_agent_service, role
) -> None:
    username = f"agent-{role.value.lower()}"
    password = "AgentRolePass123!"
    AuthService(session).create_user(username, password, role)

    response = client.post(
        "/api/v1/agent/chat",
        json={"message": "查询今日出勤"},
        headers=login_headers(client, username, password),
    )

    assert response.status_code == 200
    assert fake_agent_service.calls[-1][1].current_user.role == role


def test_agent_chat_maps_result_and_reuses_request_id(
    client, fake_agent_service
) -> None:
    response = client.post(
        "/api/v1/agent/chat",
        json={"message": "  今天哪些车辆出勤？  "},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "今天有2辆车出勤。"
    assert body["tool_calls_count"] == 1
    assert body["used_tools"] == ["get_vehicle_attendance"]
    UUID(body["request_id"])
    message, context = fake_agent_service.calls[0]
    assert message == "今天哪些车辆出勤？"
    assert context.current_user.username == "test-admin"
    assert context.request_id == body["request_id"]


@pytest.mark.parametrize(
    "message",
    ["", "   ", "中" * 4001],
)
def test_agent_chat_rejects_invalid_message(
    client, fake_agent_service, message
) -> None:
    response = client.post(
        "/api/v1/agent/chat",
        json={"message": message},
    )

    assert response.status_code == 422
    assert fake_agent_service.calls == []


def test_agent_chat_accepts_normal_chinese_input(
    client, fake_agent_service
) -> None:
    response = client.post(
        "/api/v1/agent/chat",
        json={"message": "请查询2026年9月28日的派车方案"},
    )

    assert response.status_code == 200
    assert fake_agent_service.calls[0][0] == "请查询2026年9月28日的派车方案"


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (
            AgentModelConfigurationError(),
            503,
            "AGENT_MODEL_CONFIGURATION_ERROR",
        ),
        (AgentModelTimeoutError(), 504, "AGENT_MODEL_TIMEOUT"),
        (AgentModelConnectionError(), 503, "AGENT_MODEL_CONNECTION_ERROR"),
        (AgentModelResponseError(), 502, "AGENT_MODEL_RESPONSE_ERROR"),
        (
            AgentToolNotFoundError("delete_database"),
            400,
            "AGENT_TOOL_NOT_FOUND",
        ),
        (
            AgentToolArgumentsError("get_dispatch_plan_detail"),
            400,
            "AGENT_TOOL_ARGUMENTS_ERROR",
        ),
        (
            AgentToolExecutionError("get_dispatch_plan_detail"),
            500,
            "AGENT_TOOL_EXECUTION_ERROR",
        ),
        (
            AgentMaxToolCallsError(5),
            400,
            "AGENT_MAX_TOOL_CALLS_EXCEEDED",
        ),
    ],
)
def test_agent_errors_use_existing_safe_error_response(
    client, error, status_code, code
) -> None:
    service = FakeAgentService(error=error)
    override_agent_service(service)

    response = client.post(
        "/api/v1/agent/chat",
        json={"message": "查询物流业务信息"},
    )

    assert_safe_error(response, status_code, code)


def test_missing_model_configuration_does_not_break_other_logistics_api(
    client,
) -> None:
    override_agent_service(
        FakeAgentService(error=AgentModelConfigurationError())
    )

    agent_response = client.post(
        "/api/v1/agent/chat",
        json={"message": "查询今日车辆"},
    )
    logistics_response = client.get("/api/v1/terrains")

    assert_safe_error(
        agent_response, 503, "AGENT_MODEL_CONFIGURATION_ERROR"
    )
    assert logistics_response.status_code == 200


def test_model_connection_failure_does_not_break_other_logistics_api(
    client,
) -> None:
    override_agent_service(FakeAgentService(error=AgentModelConnectionError()))

    agent_response = client.post(
        "/api/v1/agent/chat",
        json={"message": "查询今日车辆"},
    )

    assert_safe_error(agent_response, 503, "AGENT_MODEL_CONNECTION_ERROR")
    assert client.get("/api/v1/vehicle-types").status_code == 200


def test_agent_permission_does_not_open_other_post_apis(
    client, session, fake_agent_service
) -> None:
    AuthService(session).create_user(
        "agent-viewer", "AgentViewer123!", UserRole.VIEWER
    )
    headers = login_headers(client, "agent-viewer", "AgentViewer123!")

    agent_response = client.post(
        "/api/v1/agent/chat",
        json={"message": "查询今日车辆"},
        headers=headers,
    )
    terrain_write = client.post(
        "/api/v1/terrains",
        json={"code": "NORMAL", "name": "普通"},
        headers=headers,
    )
    user_write = client.post(
        "/api/v1/users",
        json={
            "username": "forbidden-user",
            "password": "Forbidden123!",
            "role": "VIEWER",
        },
        headers=headers,
    )

    assert agent_response.status_code == 200
    assert terrain_write.status_code == 403
    assert user_write.status_code == 403


def test_openapi_documents_agent_as_read_only(client, fake_agent_service) -> None:
    operation = client.get("/openapi.json").json()["paths"][
        "/api/v1/agent/chat"
    ]["post"]

    assert operation["summary"] == "使用只读物流调度助手"
    assert "不会修改任何物流业务数据" in operation["description"]
