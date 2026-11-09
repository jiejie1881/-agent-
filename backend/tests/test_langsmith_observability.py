import asyncio
import json
import os
from copy import deepcopy
from pathlib import Path
from threading import Event
from time import perf_counter
from uuid import uuid4

import pytest
from app.agent import observability as obs
from app.agent.dispatch_workflow import ShadowDispatchWorkflow
from app.agent.langchain_client import LangChainModelClient
from app.domain.enums import VehicleTypeCode
from app.models.vehicle import Vehicle, VehicleType
from app.models.vehicle_attendance import VehicleAttendance
from langgraph.graph import END, START, StateGraph
from pydantic import SecretStr

from tests import test_agent_dispatch_foundation as foundation
from tests.test_agent_dispatch_shadow import (
    ACTOR,
    REQUEST,
    FakeModel,
    settings,
    table_contents,
)

DATASET = json.loads((Path(__file__).parent / 'fixtures/langsmith_eval.json').read_text())
SENSITIVE = 'secret-canary-phone-13800138000-address-token-password'
SDK_CLIENT_FACTORY = obs._make_client


class Recorder:
    def __init__(self, fail=False):
        self.events = []
        self.fail = fail

    def create_run(self, **payload):
        self.events.append(('create', payload))
        if self.fail:
            raise ConnectionError(SENSITIVE)

    def update_run(self, **payload):
        self.events.append(('update', payload))
        if self.fail:
            raise TimeoutError(SENSITIVE)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def isolated_senders(monkeypatch):
    # No tests may accidentally upload to a real tracing service.
    monkeypatch.setattr(obs, '_senders', {})
    recorder = Recorder()
    monkeypatch.setattr(obs, '_make_client', lambda cfg: recorder)
    yield recorder
    for sender in obs._senders.values():
        sender.flush()
        sender.close()


@pytest.fixture
def resources(session):
    return foundation.resources.__wrapped__(session)


def traced_settings(**changes):
    return settings(langsmith_tracing=True,
        langsmith_api_key=SecretStr('test-only-not-a-real-langsmith-key'), **changes)


def test_defaults_and_missing_key_require_no_sdk(monkeypatch):
    assert settings().langsmith_tracing is False
    assert obs._sender(settings()) is None
    assert obs._sender(settings(langsmith_tracing=True)) is None
    assert obs._sender(traced_settings(app_environment='production',
        api_docs_enabled=False, run_migrations=False, agent_dispatch_shadow_max_cost='1',
        agent_dispatch_shadow_input_price_per_million='0', agent_dispatch_shadow_output_price_per_million='0',
        agent_dispatch_shadow_cost_currency='CNY')) is None
    assert not obs._senders


@pytest.mark.parametrize('endpoint,project', [
    ('http://api.smith.langchain.com', 'logistics-agent-dev'),
    ('https://example.invalid', 'logistics-agent-dev'),
    ('https://api.smith.langchain.com', SENSITIVE),
])
def test_unapproved_trace_targets_or_project_names_are_disabled(endpoint, project):
    assert obs._sender(traced_settings(langsmith_endpoint=endpoint, langsmith_project=project)) is None


def test_callback_drops_raw_state_names_errors_and_metadata():
    recorder = Recorder()
    sender = obs.TraceSender(lambda: recorder)
    callback = obs.SafeAgentCallback(sender, 'logistics-agent-dev', 'test', 'dispatch')
    root, child, model = uuid4(), uuid4(), uuid4()
    callback.on_chain_start({'description': SENSITIVE}, {'messages': SENSITIVE}, run_id=root, name='LangGraph', metadata={'token': SENSITIVE})
    callback.on_tool_start({'name': SENSITIVE}, SENSITIVE, run_id=child, parent_run_id=root)
    callback.on_tool_error(RuntimeError(SENSITIVE), run_id=child)
    callback.on_chat_model_start({'key': SENSITIVE}, [SENSITIVE], run_id=model, parent_run_id=root)
    callback.on_llm_end({'generations': SENSITIVE}, run_id=model)
    callback.on_chain_end({'candidate': SENSITIVE}, run_id=root)
    assert sender.flush()
    sender.close()
    payload = json.dumps(recorder.events, default=str)
    assert SENSITIVE not in payload
    starts = [event for operation, event in recorder.events if operation == 'create']
    assert len(starts) == 3 and starts[1]['parent_run_id'] == root
    assert starts[1]['trace_id'] == root
    assert starts[1]['dotted_order'].startswith(starts[0]['dotted_order'] + '.')
    assert all(event['inputs'] == {} for event in starts)
    assert any(event.get('error') == 'agent_execution_error' for _, event in recorder.events)


def test_bounded_queue_never_waits_for_slow_trace_server():
    started, release = Event(), Event()
    def factory():
        started.set()
        release.wait(2)
        return Recorder()
    sender = obs.TraceSender(factory, capacity=2)
    sender.submit('create', {})
    assert started.wait(1)
    before = perf_counter()
    for _ in range(100):
        sender.submit('create', {})
    elapsed = perf_counter() - before
    assert sender.dropped > 0 and elapsed < 0.5
    release.set()
    assert sender.flush()
    sender.close()


def test_observer_setup_failure_preserves_original_business_exception(monkeypatch):
    monkeypatch.setattr(obs, '_sender', lambda cfg: (_ for _ in ()).throw(ConnectionError(SENSITIVE)))
    class Service:
        settings = traced_settings()
        @obs.observed_agent('chat')
        async def call(self):
            raise ValueError('original-business-error')
    with pytest.raises(ValueError, match='original-business-error'):
        asyncio.run(Service().call())


def test_global_native_tracing_does_not_serialize_raw_state(monkeypatch):
    import langchain_core.tracers.langchain as manager
    monkeypatch.setenv('LANGSMITH_TRACING', 'true')
    monkeypatch.setenv('LANGCHAIN_TRACING_V2', 'true')
    monkeypatch.setenv('LANGSMITH_API_KEY', 'test-not-real')
    monkeypatch.setattr(manager, 'LangChainTracer', lambda **kw: pytest.fail('raw tracer created'))
    class Service:
        settings = settings(langsmith_tracing=False)
        @obs.observed_agent('chat')
        async def call(self):
            graph = StateGraph(dict)
            graph.add_node('model', lambda state: state)
            graph.add_edge(START, 'model')
            graph.add_edge('model', END)
            return await graph.compile().ainvoke({'raw': SENSITIVE}, obs.trace_config({}))
    assert asyncio.run(Service().call()) == {'raw': SENSITIVE}
    assert not obs._senders


def prepare_case(case, session, resources):
    scenario = case['scenario']
    if scenario == 'overweight':
        resources['demand'].quantity = 600
    if scenario == 'terrain_replan':
        kind = VehicleType(code=VehicleTypeCode.BIG_VAN, name='合成无地形许可车型', min_load=100, max_load=800, is_active=True)
        session.add(kind)
        session.flush()
        other = Vehicle(code='SYNTH-OTHER', plate_number='验收车-替代候选',
            vehicle_type_id=kind.id, driver_user_id=resources['standby'].id, is_active=True)
        session.add(other)
        session.flush()
        session.add(VehicleAttendance(date=foundation.DAY, vehicle_id=other.id, available=True))
    session.commit()
    context = foundation.context(session)
    valid = foundation.candidate(context, resources)
    outputs = [valid]
    if scenario == 'terrain_replan':
        bad = deepcopy(valid)
        bad['trips'][0].update(vehicle_id=other.id, driver_id=resources['standby'].id)
        outputs = [bad, valid]
    return context, outputs


@pytest.mark.parametrize('case', DATASET, ids=lambda case: case['id'])
@pytest.mark.parametrize('tracing', [False, True])
def test_offline_dispatch_evaluation(case, tracing, session, resources, isolated_senders):
    context, outputs = prepare_case(case, session, resources)
    before = table_contents(session)
    model = FakeModel(outputs)
    config = traced_settings(agent_dispatch_shadow_max_revisions=0 if case['scenario'] == 'overweight' else 2)
    config.langsmith_tracing = tracing
    workflow = ShadowDispatchWorkflow(model, lambda day: foundation.context(session), config)
    result = asyncio.run(workflow.run(REQUEST, ACTOR))
    assert result.status == case['expected_status'], result.model_dump()
    assert len(model.calls) == case['expected_calls']
    assert table_contents(session) == before
    if case['scenario'] == 'overweight':
        assert any(v.violation_code == 'OVERLOAD' for v in result.attempts[0].validation.violations)
    if case['scenario'] == 'terrain_replan':
        assert any(v.violation_code == 'TERRAIN_NOT_ALLOWED' for v in result.attempts[0].validation.violations)
        assert result.candidate.trips[0].vehicle_id == resources['vehicle'].id
        assert result.validation.is_valid
    if tracing:
        sender = obs._sender(config)
        assert sender.flush()
        assert sender.sent > 0 and sender.failed == 0
        events = isolated_senders.events
        assert 'validate_dispatch_candidate' in {p['name'] for op, p in events if op == 'create'}
        assert all(p.get('end_time') for op, p in events if op == 'update')
        assert any(p.get('parent_run_id') for op, p in events if op == 'create')
        assert {p['id'] for op, p in events if op == 'create'} == {p['run_id'] for op, p in events if op == 'update'}
        assert SENSITIVE not in json.dumps(events, default=str)
        assert 'foundation-driver' not in json.dumps(events, default=str)
        assert any(p.get('extra', {}).get('metadata', {}).get('business_status') == result.status
                   for op, p in events if op == 'update')
    output = os.environ.get('LANGSMITH_EVAL_OUTPUT')
    if output and tracing:
        path = Path(output)
        path.mkdir(parents=True, exist_ok=True)
        (path / (case['id'] + '.json')).write_text(json.dumps({
            'case': case, 'synthetic_context': context.model_dump(mode='json'),
            'actual': result.model_dump(mode='json'), 'model_calls': len(model.calls),
            'model_kind': 'offline_fake', 'actual_model_cost_cny': 0,
        }, ensure_ascii=False, indent=2), encoding='utf-8')


def test_trace_outage_keeps_model_count_and_business_tables(session, resources, monkeypatch):
    recorder = Recorder(fail=True)
    monkeypatch.setattr(obs, '_make_client', lambda cfg: recorder)
    context, outputs = prepare_case(DATASET[0], session, resources)
    before = table_contents(session)
    config = traced_settings()
    model = FakeModel(outputs)
    result = asyncio.run(ShadowDispatchWorkflow(model, lambda day: context, config).run(REQUEST, ACTOR))
    assert result.status == 'SUCCESS' and len(model.calls) == 1
    sender = obs._sender(config)
    assert sender.flush() and sender.failed > 0
    assert table_contents(session) == before


def test_standalone_model_keeps_raw_tracing_disabled(monkeypatch):
    import httpx
    import langchain_core.tracers.langchain as manager

    from tests.test_agent_model_client import _settings
    monkeypatch.setenv('LANGSMITH_TRACING', 'true')
    monkeypatch.setattr(manager, 'LangChainTracer', lambda **kw: pytest.fail('raw model tracer created'))
    def respond(request):
        return httpx.Response(200, json={'id':'fake','object':'chat.completion','created':0,
            'model':'test-model','choices':[{'index':0,'message':{'role':'assistant','content':'ok'},'finish_reason':'stop'}]})
    from app.agent.model_types import AgentMessageRole, AgentModelMessage
    result = asyncio.run(LangChainModelClient(_settings(), httpx.MockTransport(respond)).chat([
        AgentModelMessage(role=AgentMessageRole.USER, content=SENSITIVE)]))
    assert result.content == 'ok'


def test_actual_sdk_outbound_payload_is_scrubbed_before_transport(monkeypatch):
    import requests
    requests_seen = []
    def respond(session, request, **kwargs):
        requests_seen.append(request)
        response = requests.Response()
        response.status_code = 200
        response._content = b'{}'
        response.request = request
        response.url = request.url
        return response
    monkeypatch.setattr(requests.Session, 'send', respond)
    monkeypatch.setenv('LANGSMITH_METADATA', json.dumps({'secret': SENSITIVE}))
    client = SDK_CLIENT_FACTORY(traced_settings())
    callback = obs.SafeAgentCallback(obs.TraceSender(lambda: client), 'logistics-agent-dev', 'test', 'dispatch')
    run_id = uuid4()
    callback.on_chain_start({'key': SENSITIVE}, {'raw': SENSITIVE}, run_id=run_id, name='LangGraph')
    child = uuid4()
    callback.on_chain_start({}, {}, run_id=child, parent_run_id=run_id, name='validate_dispatch_candidate')
    callback.on_chain_end({}, run_id=child)
    callback.on_chain_end({'status': 'SUCCESS', 'candidate': SENSITIVE}, run_id=run_id)
    assert callback.sender.flush()
    callback.sender.close()
    writes = [r for r in requests_seen if r.method in {'POST', 'PATCH'}]
    assert len(writes) == 4
    bodies = [(r.body.decode() if isinstance(r.body, bytes) else r.body) for r in writes]
    assert SENSITIVE not in ''.join(bodies)
    assert all(json.loads(body).get('inputs', {}) == {} for body in bodies)
    assert all(json.loads(body).get('outputs', {}) == {} for body in bodies)
    assert all(r.url.startswith('https://api.smith.langchain.com/') for r in requests_seen)
    child_patch = next(json.loads(body) for request, body in zip(writes, bodies)
                       if request.method == 'PATCH' and json.loads(body)['id'] == str(child))
    assert child_patch['parent_run_id'] == str(run_id)
    assert child_patch['session_name'] == 'logistics-agent-dev'
    assert child_patch['name'] == 'validate_dispatch_candidate'


def test_actual_sdk_503_does_not_retry_model_or_fail_dispatch(session, resources, monkeypatch):
    import requests
    seen = []
    def unavailable(session, request, **kwargs):
        seen.append(request)
        response = requests.Response()
        response.status_code = 503
        response._content = b'{"detail":"synthetic trace outage"}'
        response.request = request
        response.url = request.url
        return response
    monkeypatch.setattr(requests.Session, 'send', unavailable)
    monkeypatch.setattr(obs, '_make_client', SDK_CLIENT_FACTORY)
    context, outputs = prepare_case(DATASET[0], session, resources)
    before = table_contents(session)
    config = traced_settings()
    model = FakeModel(outputs)
    result = asyncio.run(ShadowDispatchWorkflow(model, lambda day: context, config).run(REQUEST, ACTOR))
    sender = obs._sender(config)
    assert sender.flush(timeout=5)
    assert result.status == 'SUCCESS' and len(model.calls) == 1
    assert sender.failed == len(seen) > 0
    assert table_contents(session) == before


def test_enabled_chat_preserves_model_tool_hierarchy_and_redacts_content(monkeypatch, tmp_path, isolated_senders):
    import httpx
    from app.agent.agent_service import AgentService
    from app.agent.tool_execution import AgentToolContext
    from app.agent.tool_registry import AgentToolRegistry
    from app.domain.enums import UserRole
    from app.models.user import User

    from tests.test_agent_model_client import _settings
    from tests.test_agent_service import FakeExecutorRegistry

    config = traced_settings()
    monkeypatch.setattr(obs, 'get_settings', lambda: config)
    calls = []
    def respond(request):
        calls.append(request)
        message = {'role': 'assistant', 'content': SENSITIVE}
        if len(calls) == 1:
            message.update(content=None, tool_calls=[{'id':'test-call','type':'function',
                'function':{'name':'list_delivery_demands','arguments':json.dumps({'date':'2026-11-10'})}}])
        return httpx.Response(200, json={'id':'fake','object':'chat.completion','created':0,
            'model':'test-model','choices':[{'index':0,'message':message,'finish_reason':'stop'}]})
    executor = FakeExecutorRegistry({'list_delivery_demands': {'synthetic': SENSITIVE}})
    service = AgentService(LangChainModelClient(_settings(), httpx.MockTransport(respond)),
        AgentToolRegistry(), executor, checkpoint_path=tmp_path / 'safe-chat.sqlite3')
    actor = User(id=8, username=SENSITIVE, password_hash=SENSITIVE, role=UserRole.VIEWER, is_active=True)
    result = asyncio.run(service.chat(SENSITIVE, AgentToolContext(current_user=actor)))
    assert result.content == SENSITIVE and len(calls) == 2 and len(executor.calls) == 1
    assert obs._sender(config).flush()
    starts = [p for op, p in isolated_senders.events if op == 'create']
    assert {'chain', 'llm', 'tool'} <= {p['run_type'] for p in starts}
    assert any(p['name'] == 'list_delivery_demands' and p.get('parent_run_id') for p in starts)
    assert SENSITIVE not in json.dumps(isolated_senders.events, default=str)


def test_trace_failure_keeps_hitl_and_confirm_once(client, session, tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.domain.exceptions import AgentPendingActionError
    from app.models.audit_log import AuditLog
    from sqlalchemy import select

    from tests.test_langgraph_workflow import pending_graph

    config = traced_settings()
    monkeypatch.setattr(obs, 'get_settings', lambda: config)
    monkeypatch.setattr(obs, '_make_client', lambda cfg: Recorder(fail=True))
    monkeypatch.setattr(get_settings(), 'agent_write_tools_enabled', True)
    service, actor, conversation, _plan, _args, action = pending_graph(client, session, tmp_path)
    # No write before the existing explicit human-confirm path is invoked.
    assert session.scalar(select(AuditLog).where(AuditLog.action == 'DISPATCH_DEMAND_MOVED')) is None
    asyncio.run(service.resume_action(conversation['id'], action.id, actor, 'confirm'))
    session.commit()
    with pytest.raises(AgentPendingActionError):
        asyncio.run(service.resume_action(conversation['id'], action.id, actor, 'confirm'))
    assert len(session.scalars(select(AuditLog).where(AuditLog.action == 'DISPATCH_DEMAND_MOVED')).all()) == 1
    sender = obs._sender(config)
    assert sender.flush() and sender.failed > 0
