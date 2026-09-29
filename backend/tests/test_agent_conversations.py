from __future__ import annotations

from collections.abc import Sequence

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.agent.chat_types import AgentChatResult
from app.agent.exceptions import AgentModelTimeoutError
from app.agent.model_types import AgentMessageRole, AgentModelMessage
from app.agent.tool_execution import AgentToolContext
from app.api.agent_dependencies import get_agent_service
from app.domain.enums import AgentConversationMessageRole, UserRole
from app.main import app
from app.models.agent_conversation import (
    AgentConversation,
    AgentConversationMessage,
)
from app.models.user import User
from app.services.agent_conversation_service import AgentConversationService
from app.services.auth_service import AuthService


class FakeConversationAgentService:
    def __init__(self) -> None:
        self.responses: list[AgentChatResult] = [
            AgentChatResult(
                content="这是Agent回答。",
                tool_calls_count=1,
                used_tools=("list_dispatch_plans",),
            )
        ]
        self.error: Exception | None = None
        self.calls: list[
            tuple[str, AgentToolContext, tuple[AgentModelMessage, ...]]
        ] = []

    async def chat(
        self,
        user_message: str,
        context: AgentToolContext,
        history: Sequence[AgentModelMessage] = (),
    ) -> AgentChatResult:
        self.calls.append((user_message, context, tuple(history)))
        if self.error is not None:
            raise self.error
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


@pytest.fixture
def conversation_agent(client):
    service = FakeConversationAgentService()
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


def create_conversation(client, headers: dict[str, str] | None = None) -> dict:
    response = client.post(
        "/api/v1/agent/conversations",
        headers=headers or {},
    )
    assert response.status_code == 201
    return response.json()


def send_message(
    client,
    conversation_id: int,
    message: str,
    headers: dict[str, str] | None = None,
):
    return client.post(
        f"/api/v1/agent/conversations/{conversation_id}/messages",
        json={"message": message},
        headers=headers or {},
    )


def test_create_list_and_get_empty_conversation(
    client, conversation_agent
) -> None:
    first = create_conversation(client)
    second = create_conversation(client)

    listed = client.get("/api/v1/agent/conversations")
    detail = client.get(f"/api/v1/agent/conversations/{first['id']}")

    assert first["title"] == "新会话"
    assert first["created_at"]
    assert first["updated_at"]
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [second["id"], first["id"]]
    assert detail.status_code == 200
    assert detail.json()["messages"] == []
    assert conversation_agent.calls == []


def test_successful_message_atomically_saves_visible_pair_and_title(
    client, conversation_agent
) -> None:
    conversation = create_conversation(client)
    user_message = "今天有哪些派车方案？"
    conversation_agent.responses = [
        AgentChatResult(
            content="今天有V1和V2。",
            tool_calls_count=1,
            used_tools=("list_dispatch_plans",),
        )
    ]

    response = send_message(client, conversation["id"], user_message)
    detail = client.get(
        f"/api/v1/agent/conversations/{conversation['id']}"
    )

    assert response.status_code == 200
    assert response.json()["conversation_id"] == conversation["id"]
    assert response.json()["message"]["role"] == "ASSISTANT"
    assert response.json()["message"]["content"] == "今天有V1和V2。"
    assert response.json()["tool_calls_count"] == 1
    assert response.json()["request_id"] == conversation_agent.calls[0][1].request_id
    assert detail.json()["title"] == user_message
    assert [item["role"] for item in detail.json()["messages"]] == [
        "USER",
        "ASSISTANT",
    ]
    assert [item["content"] for item in detail.json()["messages"]] == [
        user_message,
        "今天有V1和V2。",
    ]


def test_second_turn_receives_first_visible_exchange_as_history(
    client, conversation_agent
) -> None:
    conversation = create_conversation(client)
    conversation_agent.responses = [
        AgentChatResult(content="今天有V1和V2。", tool_calls_count=1),
        AgentChatResult(content="V2方案有一个任务。", tool_calls_count=1),
    ]

    assert send_message(
        client, conversation["id"], "今天有哪些派车方案？"
    ).status_code == 200
    second = send_message(client, conversation["id"], "第二个方案详情呢？")

    assert second.status_code == 200
    second_call = conversation_agent.calls[1]
    assert second_call[0] == "第二个方案详情呢？"
    assert [message.role for message in second_call[2]] == [
        AgentMessageRole.USER,
        AgentMessageRole.ASSISTANT,
    ]
    assert [message.content for message in second_call[2]] == [
        "今天有哪些派车方案？",
        "今天有V1和V2。",
    ]


def test_messages_are_returned_in_stable_created_at_then_id_order(
    client, session, conversation_agent
) -> None:
    conversation = create_conversation(client)
    service = AgentConversationService(session, history_max_messages=20)
    current_user = session.scalar(
        select(User).where(User.username == "test-admin")
    )
    service.save_exchange(
        conversation["id"], current_user.id, "第一问", "第一答"
    )
    service.save_exchange(
        conversation["id"], current_user.id, "第二问", "第二答"
    )

    detail = client.get(
        f"/api/v1/agent/conversations/{conversation['id']}"
    ).json()

    assert [item["content"] for item in detail["messages"]] == [
        "第一问",
        "第一答",
        "第二问",
        "第二答",
    ]
    assert [item["id"] for item in detail["messages"]] == sorted(
        item["id"] for item in detail["messages"]
    )


def test_first_message_title_is_truncated_without_model_call(
    client, conversation_agent
) -> None:
    conversation = create_conversation(client)
    long_message = "长" * 60

    assert send_message(
        client, conversation["id"], long_message
    ).status_code == 200
    detail = client.get(
        f"/api/v1/agent/conversations/{conversation['id']}"
    ).json()

    assert detail["title"] == "长" * 50
    assert len(conversation_agent.calls) == 1


def test_model_failure_does_not_persist_half_exchange(
    client, conversation_agent
) -> None:
    conversation = create_conversation(client)
    conversation_agent.error = AgentModelTimeoutError()

    response = send_message(client, conversation["id"], "这条不能落库")
    detail = client.get(
        f"/api/v1/agent/conversations/{conversation['id']}"
    ).json()

    assert response.status_code == 504
    assert response.json()["code"] == "AGENT_MODEL_TIMEOUT"
    assert detail["title"] == "新会话"
    assert detail["messages"] == []


def test_only_last_twenty_messages_are_sent_but_database_keeps_all(
    client, session, conversation_agent
) -> None:
    conversation = create_conversation(client)
    current_user = session.scalar(
        select(User).where(User.username == "test-admin")
    )
    service = AgentConversationService(session, history_max_messages=20)
    for index in range(1, 16):
        service.save_exchange(
            conversation["id"],
            current_user.id,
            f"用户{index}",
            f"助手{index}",
        )

    response = send_message(client, conversation["id"], "用户16")

    assert response.status_code == 200
    history = conversation_agent.calls[0][2]
    assert len(history) == 20
    assert history[0].content == "用户6"
    assert history[-1].content == "助手15"
    detail = client.get(
        f"/api/v1/agent/conversations/{conversation['id']}"
    ).json()
    assert len(detail["messages"]) == 32
    assert detail["messages"][-2]["content"] == "用户16"


def test_other_user_cannot_read_or_send_to_conversation(
    client, session, conversation_agent
) -> None:
    AuthService(session).create_user(
        "owner", "OwnerPass123!", UserRole.VIEWER
    )
    AuthService(session).create_user(
        "intruder", "IntruderPass123!", UserRole.VIEWER
    )
    owner_headers = login_headers(client, "owner", "OwnerPass123!")
    intruder_headers = login_headers(client, "intruder", "IntruderPass123!")
    conversation = create_conversation(client, owner_headers)

    read = client.get(
        f"/api/v1/agent/conversations/{conversation['id']}",
        headers=intruder_headers,
    )
    send = send_message(
        client,
        conversation["id"],
        "尝试读取别人的上下文",
        intruder_headers,
    )
    admin_read = client.get(
        f"/api/v1/agent/conversations/{conversation['id']}"
    )

    assert read.status_code == 404
    assert send.status_code == 404
    assert admin_read.status_code == 404
    assert conversation_agent.calls == []


def test_conversation_list_contains_only_current_users_rows(
    client, session, conversation_agent
) -> None:
    AuthService(session).create_user(
        "list-a", "ListUserA123!", UserRole.VIEWER
    )
    AuthService(session).create_user(
        "list-b", "ListUserB123!", UserRole.VIEWER
    )
    headers_a = login_headers(client, "list-a", "ListUserA123!")
    headers_b = login_headers(client, "list-b", "ListUserB123!")
    own = create_conversation(client, headers_a)
    create_conversation(client, headers_b)

    listed = client.get(
        "/api/v1/agent/conversations", headers=headers_a
    ).json()

    assert [item["id"] for item in listed] == [own["id"]]


@pytest.mark.parametrize(
    "role",
    [UserRole.ADMIN, UserRole.DISPATCHER, UserRole.VIEWER],
)
def test_all_roles_can_manage_only_their_own_conversations(
    client, session, conversation_agent, role
) -> None:
    username = f"conversation-{role.value.lower()}"
    password = "ConversationRole123!"
    AuthService(session).create_user(username, password, role)
    headers = login_headers(client, username, password)

    created = create_conversation(client, headers)
    listed = client.get(
        "/api/v1/agent/conversations", headers=headers
    )

    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [created["id"]]


def test_database_rejects_blank_visible_message(client, session) -> None:
    user = session.scalar(select(User).where(User.username == "test-admin"))
    conversation = AgentConversation(user_id=user.id, title="约束测试")
    session.add(conversation)
    session.flush()
    session.add(
        AgentConversationMessage(
            conversation_id=conversation.id,
            role=AgentConversationMessageRole.USER,
            content="   ",
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_database_role_enum_is_distinct_from_model_protocol_role() -> None:
    assert AgentConversationMessageRole.USER.value == "USER"
    assert AgentMessageRole.USER.value == "user"
    assert AgentConversationMessage.__table__.c.content.type.__class__.__name__ == "Text"
