import asyncio
import json

import httpx
import pytest

from app.agent.langchain_client import LangChainModelClient
from app.agent.model_types import AgentMessageRole, AgentModelMessage
from app.agent.tool_registry import AgentToolRegistry
from app.agent.exceptions import AgentModelResponseError
from tests.test_agent_model_client import _settings


def run(handler):
    return asyncio.run(LangChainModelClient(_settings(), transport=httpx.MockTransport(handler)).chat(
        [AgentModelMessage(role=AgentMessageRole.USER, content='查询需求')],
        AgentToolRegistry().to_openai_tools()))


def response(message):
    return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 0,
        'model': 'test-model', 'choices': [{'index': 0, 'message': message, 'finish_reason': 'stop'}]})


def test_langchain_supplies_nine_schemas_and_normalizes_tool_calls():
    def handler(request):
        body = json.loads(request.content)
        assert len(body['tools']) == 9
        assert request.headers['authorization'] == 'Bearer sk-test-secret-key'
        return response({'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': 'call1', 'type': 'function', 'function': {'name': 'list_delivery_demands', 'arguments': '{"date":"2026-10-08"}'}}]})
    result = run(handler)
    assert result.tool_calls[0].arguments == {'date': '2026-10-08'}
    assert result.tool_calls[0].id == 'call1'


def test_langchain_plain_answer():
    assert run(lambda req: response({'role': 'assistant', 'content': '你好'})).content == '你好'


def test_langchain_invalid_tool_json_is_not_silently_dropped():
    with pytest.raises(AgentModelResponseError):
        run(lambda req: response({'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': 'bad', 'type': 'function', 'function': {'name': 'list_delivery_demands', 'arguments': '{'}}]}))


def test_langchain_provider_error_does_not_leak_credentials():
    with pytest.raises(AgentModelResponseError) as error:
        run(lambda req: httpx.Response(429, json={'error': {'message': 'sk-test-secret-key quota', 'type': 'rate_limit_error'}}))
    assert 'sk-test-secret-key' not in str(error.value)


@pytest.mark.parametrize('payload', [{}, {'choices': []}, {'choices': None}, {'choices': [{'message': None}]}])
def test_langchain_malformed_provider_response_has_explicit_error(payload):
    with pytest.raises(AgentModelResponseError):
        run(lambda req: httpx.Response(200, json=payload))
