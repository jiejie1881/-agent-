"""Streaming contract tests with clearly synthetic provider output."""
import asyncio
import json
from types import SimpleNamespace
import httpx
import pytest
from app.agent.stream_events import emit
from app.api.v1.endpoints.agent_stream import stream_message, cancel_stream, active
from app.schemas.agent import AgentChatRequest


def test_first_event_and_token_precede_completion_and_cancel():
    async def scenario():
        gate = asyncio.Event()
        cancelled = []
        class Conversations:
            def get_model_history(self, cid, uid):
                assert (cid, uid) == (7, 1)
                return ()
            def get_owned(self, cid, uid):
                assert (cid, uid) == (7, 1)
            def save_exchange(self, *args):
                raise AssertionError('Cancelled exchange must not commit')
        class Agent:
            graph_store = SimpleNamespace(request_cancellation=lambda *args: cancelled.append(args))
            async def chat(self, *args):
                emit('agent_status', {'execution_id': 'run-test', 'status': 'RUNNING'})
                emit('token', {'text': '增量'})
                await gate.wait()
        user = SimpleNamespace(id=1)
        conv = Conversations()
        response = await stream_message(7, AgentChatRequest(message='测试'), user, conv, Agent())
        iterator = response.body_iterator
        frames = [await asyncio.wait_for(anext(iterator), 1) for _ in range(3)]
        assert 'message_start' in frames[0]
        assert '增量' in frames[2]
        assert not gate.is_set()
        result = await cancel_stream(7, user, conv)
        assert result['requested'] and not result['cleanup_confirmed']
        remaining = [frame async for frame in iterator]
        assert any('event: cancelled' in frame for frame in remaining)
        assert cancelled == [('run-test', 1, 7)]
        assert (1, 7) not in active
    asyncio.run(scenario())


def test_disconnect_cancels_inflight_task():
    async def scenario():
        cancelled = asyncio.Event()
        class Agent:
            async def chat(self, *args):
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
        conv = SimpleNamespace(get_model_history=lambda *args: ())
        response = await stream_message(8, AgentChatRequest(message='测试'), SimpleNamespace(id=2), conv, Agent())
        await anext(response.body_iterator)
        await response.body_iterator.aclose()
        assert cancelled.is_set()
        assert (2, 8) not in active
    asyncio.run(scenario())


def test_stream_budget_chunks_are_not_buffered(isolated_model_budget):
    from app.core.model_budget import BudgetedAsyncTransport
    async def scenario():
        gate = asyncio.Event()
        class Chunks(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'first'
                await gate.wait()
                yield b'last'
        transport = BudgetedAsyncTransport(isolated_model_budget, 'https://model.test/chat/completions',
            'chat_stream', httpx.MockTransport(lambda request: httpx.Response(200, stream=Chunks())))
        async with httpx.AsyncClient(transport=transport) as client:
            async with client.stream('POST', 'https://model.test/chat/completions',
                json={'stream': True, 'max_tokens': 8}) as response:
                chunks = response.aiter_bytes()
                assert await asyncio.wait_for(anext(chunks), 1) == b'first'
                assert not gate.is_set()
                gate.set()
                assert await anext(chunks) == b'last'
    asyncio.run(scenario())


@pytest.mark.parametrize('prices', [None, (1.0, 2.0)])
def test_langchain_stream_emits_actual_deltas_and_usage(prices):
    from app.agent.langchain_client import LangChainModelClient
    from app.agent.model_types import AgentModelMessage, AgentMessageRole
    from app.agent.stream_events import sink
    from tests.test_agent_model_client import _settings
    async def scenario():
        events = []
        class Chunks(httpx.AsyncByteStream):
            async def __aiter__(self):
                for text in ['你', '好']:
                    body = {'id': 'test', 'object': 'chat.completion.chunk', 'created': 0, 'model': 'test-model',
                        'choices': [{'index': 0, 'delta': {'content': text}, 'finish_reason': None}]}
                    yield ('data: ' + json.dumps(body) + '\n\n').encode()
                yield ('data: ' + json.dumps({'id': 'test', 'object': 'chat.completion.chunk', 'created': 0,
                    'model': 'test-model', 'choices': [], 'usage': {'prompt_tokens': 3, 'completion_tokens': 2, 'total_tokens': 5}}) + '\n\n').encode()
                yield b'data: [DONE]\n\n'
        def handler(request):
            assert json.loads(request.content)['stream'] is True
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Chunks())
        settings = _settings()
        if prices:
            settings.agent_input_price_per_million, settings.agent_output_price_per_million = prices
            settings.agent_cost_currency = 'CNY'
        model = LangChainModelClient(settings, transport=httpx.MockTransport(handler))
        model.phase, model.stream_final = 'summary', True
        token = sink.set(lambda kind, payload: events.append((kind, payload)))
        try:
            result = await model.chat([AgentModelMessage(role=AgentMessageRole.USER, content='测试')], [])
        finally:
            sink.reset(token)
        assert result.content == '你好'
        assert result.token_usage.total_tokens == 5
        assert [payload['text'] for kind, payload in events if kind == 'token'] == ['你', '好']
        metrics = [payload for kind, payload in events if kind == 'model_metrics'][0]
        assert metrics['ttft_ms'] is not None
        assert metrics['cost'] == pytest.approx(0.000007) if prices else metrics['cost'] == 'UNKNOWN'
    asyncio.run(scenario())


def test_public_event_journal_survives_reopen_and_isolates_users(tmp_path):
    from app.agent.stream_store import StreamStore
    path = tmp_path / 'checkpoint.sqlite'
    store = StreamStore(path)
    event = {'conversation_id': 3, 'message_id': 'message', 'sequence': 1, 'payload': {}}
    store.append(1, event)
    reopened = StreamStore(path)
    assert reopened.read(1, 3, 'message') == [event]
    assert reopened.read(2, 3, 'message') == []
    assert reopened.read(1, 3, 'message', after=1) == []


def test_stream_api_ownership_persistence_and_history_pagination(client, session):
    from app.main import app
    from app.api.agent_dependencies import get_agent_service
    from app.agent.chat_types import AgentChatResult
    from app.models.agent_conversation import AgentConversation
    class Agent:
        async def chat(self, message, context, history):
            emit('token', {'text': '回答'})
            return AgentChatResult(content='回答', tool_calls_count=0, used_tools=())
    app.dependency_overrides[get_agent_service] = lambda: Agent()
    cid = client.post('/api/v1/agent/conversations').json()['id']
    response = client.post(f'/api/v1/agent/conversations/{cid}/stream', json={'message': '问题'})
    assert response.status_code == 200
    assert 'event: token' in response.text and 'event: message_complete' in response.text
    assert 'text/event-stream' in response.headers['content-type']
    page = client.get(f'/api/v1/agent/conversations/{cid}/messages/page?offset=1&limit=1')
    assert page.status_code == 200 and len(page.json()) == 1 and page.json()[0]['content'] == '回答'
    foreign = AgentConversation(user_id=999, title='other')
    session.add(foreign); session.commit()
    assert client.post(f'/api/v1/agent/conversations/{foreign.id}/stream', json={'message': '问题'}).status_code == 404
    assert client.get(f'/api/v1/agent/conversations/{foreign.id}/stream/events?message_id=x').status_code == 404
    headers = {'Idempotency-Key': 'stable-test-operation'}
    assert client.post(f'/api/v1/agent/conversations/{cid}/stream', json={'message': '问题'}, headers=headers).status_code == 200
    assert client.post(f'/api/v1/agent/conversations/{cid}/stream', json={'message': '问题'}, headers=headers).status_code == 409
    metrics = client.get(f'/api/v1/agent/conversations/{cid}/stream/metrics').json()
    assert metrics['run_count'] == 2
    assert metrics['model_metrics_scope'] == 'streamed_final_model_calls_only'
    assert metrics['measured_model_calls'] == []
