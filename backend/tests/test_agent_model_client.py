import asyncio
import json
import logging

import httpx
import pytest

from app.agent.exceptions import (
    AgentModelConfigurationError,
    AgentModelConnectionError,
    AgentModelResponseError,
    AgentModelTimeoutError,
)
from app.agent.model_client import OpenAICompatibleModelClient
from app.agent.model_types import (
    AgentMessageRole,
    AgentModelMessage,
    AgentToolCall,
)
from app.core.config import Settings


def _settings(**overrides) -> Settings:
    values = {
        "database_url": "sqlite+pysqlite:///:memory:",
        "jwt_secret_key": "test-only-secret-key-with-at-least-32-characters",
        "agent_provider": "openai-compatible",
        "agent_model": "test-model",
        "agent_api_key": "sk-test-secret-key",
        "agent_base_url": "https://model.example/v1",
        "agent_timeout": 2,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _response(message: dict, finish_reason: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {"message": message, "finish_reason": finish_reason}
            ]
        },
    )


def _chat(
    handler,
    messages: list[AgentModelMessage] | None = None,
    tools=None,
    settings: Settings | None = None,
):
    client = OpenAICompatibleModelClient(
        settings or _settings(),
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(
        client.chat(
            messages
            or [
                AgentModelMessage(
                    role=AgentMessageRole.USER,
                    content="今天共有多少配送需求？",
                )
            ],
            tools=tools,
        )
    )
    return client, result


def test_chat_normalizes_text_response_and_request() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer sk-test-secret-key"
        return _response({"role": "assistant", "content": "今天共有10个配送需求。"})

    _, result = _chat(handler)

    assert result.content == "今天共有10个配送需求。"
    assert result.tool_calls == ()
    assert result.has_tool_calls is False
    assert captured["model"] == "test-model"
    assert captured["messages"][0] == {
        "role": "user",
        "content": "今天共有多少配送需求？",
    }


def test_chat_normalizes_single_tool_call_and_passes_tools() -> None:
    tool_definition = {
        "type": "function",
        "function": {
            "name": "get_vehicle_attendance",
            "description": "查询车辆出勤",
            "parameters": {"type": "object"},
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["tools"] == [tool_definition]
        return _response(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_vehicle_attendance",
                            "arguments": '{"date":"2026-09-28"}',
                        },
                    }
                ],
            },
            finish_reason="tool_calls",
        )

    _, result = _chat(handler, tools=[tool_definition])

    assert result.has_tool_calls is True
    assert result.finish_reason == "tool_calls"
    assert result.tool_calls == (
        AgentToolCall(
            id="call_1",
            name="get_vehicle_attendance",
            arguments={"date": "2026-09-28"},
        ),
    )


def test_chat_normalizes_multiple_tool_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _response(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "list_delivery_demands",
                            "arguments": {"date": "2026-09-28"},
                        },
                    },
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "list_dispatch_plans",
                            "arguments": '{"delivery_date":"2026-09-28"}',
                        },
                    },
                ],
            },
            finish_reason="tool_calls",
        )

    _, result = _chat(handler)

    assert [item.id for item in result.tool_calls] == ["call_1", "call_2"]
    assert [item.name for item in result.tool_calls] == [
        "list_delivery_demands",
        "list_dispatch_plans",
    ]


def test_chat_rejects_invalid_tool_arguments_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _response(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_bad",
                        "type": "function",
                        "function": {
                            "name": "get_vehicle_attendance",
                            "arguments": "{not-json}",
                        },
                    }
                ],
            }
        )

    with pytest.raises(AgentModelResponseError) as exc_info:
        _chat(handler)

    assert exc_info.value.code == "AGENT_MODEL_RESPONSE_ERROR"
    assert "合法JSON" in str(exc_info.value)


def test_chat_converts_provider_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider timeout", request=request)

    with pytest.raises(AgentModelTimeoutError) as exc_info:
        _chat(handler)

    assert exc_info.value.code == "AGENT_MODEL_TIMEOUT"


def test_chat_converts_provider_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(AgentModelConnectionError) as exc_info:
        _chat(handler)

    assert exc_info.value.code == "AGENT_MODEL_CONNECTION_ERROR"


def test_missing_api_key_fails_only_when_agent_is_called() -> None:
    settings = _settings(agent_api_key=None)
    client = OpenAICompatibleModelClient(settings)

    with pytest.raises(AgentModelConfigurationError) as exc_info:
        asyncio.run(
            client.chat(
                [AgentModelMessage(role=AgentMessageRole.USER, content="你好")]
            )
        )

    assert exc_info.value.message == "AGENT_API_KEY未配置"

    settings_without_agent = Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        jwt_secret_key="test-only-secret-key-with-at-least-32-characters",
    )
    assert settings_without_agent.agent_api_key is None


def test_api_key_is_not_exposed_by_client_or_provider_error(caplog) -> None:
    secret = "sk-test-secret-key"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            f"failed with credential {secret}", request=request
        )

    client = OpenAICompatibleModelClient(
        _settings(agent_api_key=secret),
        transport=httpx.MockTransport(handler),
    )
    with caplog.at_level(logging.DEBUG), pytest.raises(
        AgentModelConnectionError
    ) as exc_info:
        asyncio.run(
            client.chat(
                [AgentModelMessage(role=AgentMessageRole.USER, content="你好")]
            )
        )

    assert secret not in str(exc_info.value)
    assert secret not in repr(client)
    assert secret not in caplog.text


def test_provider_error_response_does_not_expose_api_key() -> None:
    secret = "sk-test-secret-key"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={"error": f"upstream rejected {secret}"},
        )

    with pytest.raises(AgentModelResponseError) as exc_info:
        _chat(handler, settings=_settings(agent_api_key=secret))

    assert secret not in str(exc_info.value)
    assert exc_info.value.message == "Agent模型服务返回错误状态"


def test_provider_invalid_model_uses_safe_configuration_hint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "code": 20012,
                "message": "Model does not exist. Please check it carefully.",
                "data": None,
            },
        )

    with pytest.raises(AgentModelResponseError) as exc_info:
        _chat(handler)

    assert exc_info.value.message == (
        "Agent模型不存在或不可用，请检查AGENT_MODEL"
    )


@pytest.mark.parametrize(
    ("status_code", "expected_message"),
    [
        (401, "Agent模型认证失败，请检查AGENT_API_KEY"),
        (429, "Agent模型请求过于频繁，请稍后重试"),
        (404, "Agent模型接口不存在，请检查AGENT_BASE_URL"),
    ],
)
def test_provider_http_status_uses_safe_actionable_message(
    status_code: int,
    expected_message: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"message": "provider detail"})

    with pytest.raises(AgentModelResponseError) as exc_info:
        _chat(handler)

    assert exc_info.value.message == expected_message


def test_malformed_provider_response_uses_unified_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    with pytest.raises(AgentModelResponseError) as exc_info:
        _chat(handler)

    assert exc_info.value.code == "AGENT_MODEL_RESPONSE_ERROR"


def test_all_message_roles_are_serialized_without_raw_dicts() -> None:
    messages = [
        AgentModelMessage(role=AgentMessageRole.SYSTEM, content="只进行只读查询"),
        AgentModelMessage(role=AgentMessageRole.USER, content="查询今天车辆"),
        AgentModelMessage(
            role=AgentMessageRole.ASSISTANT,
            content=None,
            tool_calls=(
                AgentToolCall(
                    id="call_1",
                    name="get_vehicle_attendance",
                    arguments={"date": "2026-09-28"},
                ),
            ),
        ),
        AgentModelMessage(
            role=AgentMessageRole.TOOL,
            content='{"vehicles":[]}',
            tool_call_id="call_1",
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert [item["role"] for item in payload["messages"]] == [
            "system",
            "user",
            "assistant",
            "tool",
        ]
        assert payload["messages"][2]["tool_calls"][0]["function"][
            "arguments"
        ] == '{"date":"2026-09-28"}'
        assert payload["messages"][3]["tool_call_id"] == "call_1"
        return _response({"role": "assistant", "content": "今天没有出勤车辆。"})

    _, result = _chat(handler, messages=messages)
    assert result.content == "今天没有出勤车辆。"
