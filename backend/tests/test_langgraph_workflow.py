"""Run legacy contracts unchanged against StateGraph, then test durable HITL."""
import asyncio
import inspect
import json

import pytest
from sqlalchemy import select

from app.agent.agent_service import AgentService as LangGraphAgentService
from app.agent.model_types import AgentModelResponse
from app.agent.tool_execution import AgentToolContext
from app.domain.enums import UserRole
from app.domain.exceptions import (
    AgentPendingActionError,
    NotFoundError,
    PermissionDeniedError,
)
from app.models.audit_log import AuditLog
from app.services.auth_service import AuthService
from tests import test_agent_service as contracts
from tests.test_agent_phase2 import (
    WriteCallModel,
    build_pending_service,
    current_admin,
    move_arguments,
)
from tests.test_dispatch_plan_adjustment import generate_adjustable_plan

CONTRACTS = [name for name, fn in vars(contracts).items()
             if name.startswith('test_') and callable(fn)
             and list(inspect.signature(fn).parameters) == ['tool_context']]


@pytest.fixture(autouse=True)
def opt_in_write_graph_contracts(request, monkeypatch):
    if 'client' in request.fixturenames:
        from app.core.config import get_settings
        monkeypatch.setattr(get_settings(), 'agent_write_tools_enabled', True)


@pytest.mark.parametrize('contract', CONTRACTS)
def test_existing_contract_against_stategraph(contract, monkeypatch, tmp_path):
    monkeypatch.setattr(contracts, 'AgentService', lambda *a, **kw:
                        LangGraphAgentService(*a, checkpoint_path=tmp_path / 'graph.sqlite3', **kw))
    context = AgentToolContext(current_user=contracts.User(
        id=8, username='viewer', password_hash='never-serialize-this-password',
        role=UserRole.VIEWER, is_active=True), request_id='equivalence')
    getattr(contracts, contract)(context)


def pending_graph(client, session, tmp_path):
    _, plan, *_ = generate_adjustable_plan(client, [100, 100, 50, 50])
    conversation = client.post('/api/v1/agent/conversations').json()
    pending, registry, executors = build_pending_service(session)
    args, actor = move_arguments(plan), current_admin(session)
    service = LangGraphAgentService(WriteCallModel(args), registry, executors,
        pending_action_service=pending, checkpoint_path=tmp_path / 'graph.sqlite3')
    result = asyncio.run(service.chat('移动需求', AgentToolContext(
        current_user=actor, conversation_id=conversation['id'])))
    session.commit()
    assert move_arguments(client.get(f"/api/v1/dispatch-plans/{plan['id']}").json()) == args
    return service, actor, conversation, plan, args, result.pending_actions[0]


def test_checkpoint_restart_confirm_once_and_no_credentials(client, session, tmp_path):
    service, actor, conversation, plan, args, action = pending_graph(client, session, tmp_path)
    assert service.graph_store.path.is_file()
    resumed = LangGraphAgentService(contracts.FakeModelClient([]), service.tool_registry,
        service.executor_registry, pending_action_service=service.pending_action_service,
        checkpoint_path=service.graph_store.path)
    result = asyncio.run(resumed.resume_action(conversation['id'], action.id, actor, 'confirm'))
    assert result['status'] == 'executed'
    target = next(o for o in client.get(f"/api/v1/dispatch-plans/{plan['id']}").json()['orders']
                  if o['id'] == args['target_order_id'])
    assert args['delivery_demand_id'] in [d['delivery_demand_id'] for d in target['details']]
    with pytest.raises(AgentPendingActionError):
        asyncio.run(resumed.resume_action(conversation['id'], action.id, actor, 'confirm'))
    assert len(session.scalars(select(AuditLog).where(AuditLog.action == 'DISPATCH_DEMAND_MOVED')).all()) == 1
    assert actor.password_hash.encode() not in service.graph_store.path.read_bytes()


def test_checkpoint_cancel_and_owner_isolation(client, session, tmp_path):
    service, actor, conversation, plan, args, action = pending_graph(client, session, tmp_path)
    other = AuthService(session).create_user('graph-other', 'OtherPass123!', UserRole.ADMIN)
    with pytest.raises(NotFoundError):
        asyncio.run(service.resume_action(conversation['id'], action.id, other, 'confirm'))
    other_conversation = client.post('/api/v1/agent/conversations').json()
    with pytest.raises(NotFoundError):
        asyncio.run(service.resume_action(other_conversation['id'], action.id, actor, 'confirm'))
    assert asyncio.run(service.resume_action(conversation['id'], action.id, actor, 'cancel')) == {'status': 'cancelled'}
    assert move_arguments(client.get(f"/api/v1/dispatch-plans/{plan['id']}").json()) == args
    assert session.scalar(select(AuditLog).where(AuditLog.action == 'DISPATCH_DEMAND_MOVED')) is None


def test_checkpoint_rechecks_current_permission(client, session, tmp_path):
    service, actor, conversation, plan, args, action = pending_graph(client, session, tmp_path)
    actor.role = UserRole.VIEWER
    session.commit()
    with pytest.raises(PermissionDeniedError):
        asyncio.run(service.resume_action(conversation['id'], action.id, actor, 'confirm'))
    actual = service.pending_action_service.dispatch_plan_service.get(plan['id'])
    source = next(order for order in actual.orders if order.id == args['source_order_id'])
    assert args['delivery_demand_id'] in [detail.delivery_demand_id for detail in source.details]
    assert asyncio.run(service.resume_action(conversation['id'], action.id, actor, 'cancel')) == {'status': 'cancelled'}


def test_database_commit_wins_over_stale_checkpoint(client, session, tmp_path):
    service, actor, conversation, _plan, _args, action = pending_graph(client, session, tmp_path)
    # Simulate a worker that committed business execution but died before saving
    # its final checkpoint. Retrying must not execute or audit again.
    asyncio.run(service.pending_action_service.confirm(conversation['id'], action.id, actor))
    with pytest.raises(AgentPendingActionError) as error:
        asyncio.run(service.resume_action(conversation['id'], action.id, actor, 'confirm'))
    assert error.value.code == 'AGENT_ACTION_ALREADY_EXECUTED'
    assert len(session.scalars(select(AuditLog).where(AuditLog.action == 'DISPATCH_DEMAND_MOVED')).all()) == 1


def test_pending_claim_is_conditional(client, session, tmp_path):
    from app.domain.enums import AgentPendingActionStatus
    service, actor, conversation, _, _, action = pending_graph(client, session, tmp_path)
    repository = service.pending_action_service.repository
    assert repository.claim_pending(action.id, actor.id, conversation['id'], AgentPendingActionStatus.CONFIRMED)
    assert not repository.claim_pending(action.id, actor.id, conversation['id'], AgentPendingActionStatus.CONFIRMED)
    session.rollback()


def test_old_checkpoint_cannot_attach_to_reused_business_id(client, session, tmp_path):
    from datetime import timedelta
    service, actor, conversation, _, _, action = pending_graph(client, session, tmp_path)
    record = service.pending_action_service.repository.get(action.id)
    record.created_at += timedelta(seconds=1)
    session.commit()
    assert asyncio.run(service.resume_action(conversation['id'], action.id, actor, 'confirm')) is None
    assert session.scalar(select(AuditLog).where(AuditLog.action == 'DISPATCH_DEMAND_MOVED')) is None


def test_api_resumes_graph_then_rejects_repeat_confirmation(client, session, tmp_path):
    from app.api.agent_dependencies import get_agent_service
    from app.main import app
    service, _actor, conversation, _plan, _args, action = pending_graph(client, session, tmp_path)
    app.dependency_overrides[get_agent_service] = lambda: service
    endpoint = f"/api/v1/agent/conversations/{conversation['id']}/pending-actions/{action.id}/confirm"
    result = client.post(endpoint)
    assert result.status_code == 200, result.json()
    assert result.json()['action']['status'] == 'EXECUTED'
    assert client.post(endpoint).status_code == 409


def test_graph_cancel_plan_write_waits_for_explicit_confirmation(client, session, tmp_path):
    from app.agent.model_types import AgentToolCall
    _, plan, *_ = generate_adjustable_plan(client, [100, 100])
    conversation = client.post('/api/v1/agent/conversations').json()
    pending, registry, executors = build_pending_service(session)
    service = LangGraphAgentService(contracts.FakeModelClient([
        AgentModelResponse(tool_calls=(AgentToolCall(id='cancel1', name='cancel_dispatch_plan', arguments={'plan_id': plan['id']}),)),
        AgentModelResponse(content='请人工确认取消。')]), registry, executors,
        pending_action_service=pending, checkpoint_path=tmp_path / 'graph.sqlite3')
    actor = current_admin(session)
    result = asyncio.run(service.chat('取消方案', AgentToolContext(current_user=actor, conversation_id=conversation['id'])))
    session.commit()
    assert pending.dispatch_plan_service.get(plan['id']).status.value == 'DRAFT'
    asyncio.run(service.resume_action(conversation['id'], result.pending_actions[0].id, actor, 'confirm'))
    assert pending.dispatch_plan_service.get(plan['id']).status.value == 'CANCELLED'
    assert session.scalar(select(AuditLog).where(AuditLog.action == 'DISPATCH_PLAN_CANCELLED')) is not None


@pytest.mark.parametrize('error', [contracts.AgentModelTimeoutError(), contracts.AgentModelConnectionError(), contracts.AgentModelResponseError()])
def test_graph_propagates_model_errors(tmp_path, error):
    executor = contracts.FakeExecutorRegistry()
    service = LangGraphAgentService(contracts.FakeModelClient([error]), contracts.AgentToolRegistry(),
        executor, checkpoint_path=tmp_path / 'graph.sqlite3')
    with pytest.raises(type(error)):
        asyncio.run(service.chat('查询', AgentToolContext(current_user=contracts.User(id=1))))
    assert executor.calls == []


@pytest.mark.parametrize('content', [None, '', '   '])
def test_graph_rejects_empty_model_answer(tmp_path, content):
    service = LangGraphAgentService(contracts.FakeModelClient([AgentModelResponse(content=content)]),
        contracts.AgentToolRegistry(), contracts.FakeExecutorRegistry(), checkpoint_path=tmp_path / 'graph.sqlite3')
    with pytest.raises(contracts.AgentModelResponseError):
        asyncio.run(service.chat('查询', AgentToolContext(current_user=contracts.User(id=1))))


@pytest.mark.parametrize('size', [1, 2, 3])
@pytest.mark.parametrize('batched', [False, True])
def test_tool_budget_allows_three_reads_and_synthesis(tmp_path, size, batched):
    calls = [
        contracts.tool_call('demands', 'list_delivery_demands', {'date': '2026-10-09'}),
        contracts.tool_call('plan', 'get_dispatch_plan_detail', {'plan_id': 2}),
        contracts.tool_call('rag', 'search_knowledge_base', {'query': '发布前校验规则'}),
    ][:size]
    responses = ([AgentModelResponse(tool_calls=tuple(calls))] if batched else
                 [AgentModelResponse(tool_calls=(call,)) for call in calls])
    model = contracts.FakeModelClient([*responses, AgentModelResponse(content='依据结果回答')])
    executor = contracts.FakeExecutorRegistry()
    service = LangGraphAgentService(model, contracts.AgentToolRegistry(), executor,
        max_tool_calls=size, checkpoint_path=tmp_path / 'graph.sqlite3')
    result = asyncio.run(service.chat('查询', AgentToolContext(current_user=contracts.User(id=1))))
    assert result.tool_calls_count == size
    assert result.used_tools == tuple(call.name for call in calls)
    assert len(executor.calls) == size
    assert model.calls[-1][1] == ()
    assert '预算已耗尽' in model.calls[-1][0][0].content
    assert [item.tool_call_id for item in model.calls[-1][0] if item.role.value == 'tool'] == [call.id for call in calls]


def test_identical_reads_reuse_result_but_remain_bounded(tmp_path):
    calls = [contracts.tool_call(str(i), 'get_dispatch_plan_detail', {'plan_id': 2}) for i in range(3)]
    model = contracts.FakeModelClient([
        *[AgentModelResponse(tool_calls=(call,)) for call in calls],
        AgentModelResponse(content='不应执行'),
    ])
    executor = contracts.FakeExecutorRegistry({'get_dispatch_plan_detail': {'id': 2}})
    service = LangGraphAgentService(model, contracts.AgentToolRegistry(), executor,
        max_tool_calls=2, checkpoint_path=tmp_path / 'graph.sqlite3')
    with pytest.raises(contracts.AgentMaxToolCallsError):
        asyncio.run(service.chat('查询', AgentToolContext(current_user=contracts.User(id=1))))
    assert len(executor.calls) == 1
    assert model.calls[-1][1] == ()
    results = [json.loads(m.content) for m in model.calls[-1][0] if m.role.value == 'tool']
    assert len(results) == 2 and results[0] == results[1]


def test_new_message_resets_budget_and_read_cache(tmp_path):
    call = contracts.tool_call('plan', 'get_dispatch_plan_detail', {'plan_id': 2})
    model = contracts.FakeModelClient([
        AgentModelResponse(tool_calls=(call,)), AgentModelResponse(content='第一次'),
        AgentModelResponse(tool_calls=(call,)), AgentModelResponse(content='第二次'),
    ])
    executor = contracts.FakeExecutorRegistry()
    service = LangGraphAgentService(model, contracts.AgentToolRegistry(), executor,
        max_tool_calls=1, checkpoint_path=tmp_path / 'graph.sqlite3')
    context = AgentToolContext(current_user=contracts.User(id=1))
    first = asyncio.run(service.chat('第一次', context))
    history = [contracts.AgentModelMessage(role='user', content='第一次'),
               contracts.AgentModelMessage(role='assistant', content=first.content)]
    second = asyncio.run(service.chat('第二次', context, history=history))
    assert first.tool_calls_count == second.tool_calls_count == 1
    assert len(executor.calls) == 2
    assert len(model.calls[2][1]) == 7


def test_changed_read_arguments_are_not_cached(tmp_path):
    model = contracts.FakeModelClient([
        AgentModelResponse(tool_calls=tuple(contracts.tool_call(str(i), 'get_dispatch_plan_detail', {'plan_id': i}) for i in (1, 2))),
        AgentModelResponse(content='完成'),
    ])
    executor = contracts.FakeExecutorRegistry()
    service = LangGraphAgentService(model, contracts.AgentToolRegistry(), executor,
        checkpoint_path=tmp_path / 'graph.sqlite3')
    asyncio.run(service.chat('查询', AgentToolContext(current_user=contracts.User(id=1))))
    assert [args['plan_id'] for _, args, _ in executor.calls] == [1, 2]
