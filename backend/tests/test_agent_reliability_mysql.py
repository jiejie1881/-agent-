"""Actual MySQL reliability contracts; run only via the attested owned runner.

The graph checkpoint is SQLite. These tests verify its relationship with real
MySQL business transactions, and do not claim a MySQL LangGraph checkpointer.
"""
import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.agent.agent_service import AgentService
from app.agent.tool_execution import AgentToolContext
from app.domain.enums import AgentPendingActionStatus
from app.domain.exceptions import AgentPendingActionError
from app.models.agent_pending_action import AgentPendingAction
from app.models.audit_log import AuditLog
from app.models.dispatch_plan import DispatchOrderDetail, DispatchPlan
from app.models.user import User
from tests.test_agent_phase2 import build_pending_service, create_move_action, current_admin
from tests.test_agent_task_orchestration import ScriptedPlanner, service, step
from tests.test_langgraph_workflow import pending_graph
from tests.test_agent_service import FakeModelClient

pytestmark = pytest.mark.skipif(
    os.environ.get("AGENT_MYSQL_ISOLATED") != "1",
    reason="Requires the dedicated identity-attested MySQL executor; never use a business database",
)


@pytest.fixture(autouse=True)
def opt_in_owned_mysql_writes(monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "agent_write_tools_enabled", True)


def movement_audits(session):
    return session.scalars(select(AuditLog).where(AuditLog.action == "DISPATCH_DEMAND_MOVED")).all()


def test_mysql_identity_and_owned_schema(mysql_engine, mysql_identity):
    assert mysql_engine.dialect.name == "mysql"
    assert mysql_identity["database"] == "agent_reliability_20261101"
    assert mysql_identity["server_uuid"] == os.environ["AGENT_MYSQL_EXPECTED_UUID"]
    assert mysql_identity["hostname"] == os.environ["AGENT_MYSQL_EXPECTED_HOSTNAME"]
    assert mysql_identity["version"].startswith("8.4.")
    assert {"agent_pending_actions", "audit_logs", "dispatch_plans"}.issubset(
        inspect(mysql_engine).get_table_names()
    )


def test_mysql_business_write_and_audit_rollback_together(client, session, monkeypatch):
    pending, actor, conversation, _plan, arguments, action = create_move_action(client, session)
    original = pending.executor_registry.execute

    async def fail_after_real_tool(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("synthetic failure after real business tool before commit")

    monkeypatch.setattr(pending.executor_registry, "execute", fail_after_real_tool)
    with pytest.raises(RuntimeError):
        asyncio.run(pending.confirm(conversation["id"], action.id, actor))
    session.expire_all()
    detail = session.scalar(select(DispatchOrderDetail).where(
        DispatchOrderDetail.delivery_demand_id == arguments["delivery_demand_id"]
    ))
    assert detail.dispatch_order_id == arguments["source_order_id"]
    assert movement_audits(session) == []
    assert session.get(AgentPendingAction, action.id).status == AgentPendingActionStatus.FAILED


def test_mysql_simultaneous_confirmation_has_one_commit_and_one_audit(client, session, mysql_engine):
    _pending, actor, conversation, _plan, arguments, action = create_move_action(client, session)
    actor_id, action_id, conversation_id = actor.id, action.id, conversation["id"]
    session.commit()
    barrier = Barrier(2, timeout=15)

    def confirm_in_fresh_session():
        with Session(mysql_engine, expire_on_commit=False) as local:
            local_actor = local.get(User, actor_id)
            pending, _registry, _executors = build_pending_service(local)
            barrier.wait()
            try:
                executed, _result = asyncio.run(pending.confirm(conversation_id, action_id, local_actor))
                return executed.status.value
            except AgentPendingActionError as error:
                local.rollback()
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(confirm_in_fresh_session) for _ in range(2)]
        outcomes = [future.result(timeout=40) for future in futures]
    assert outcomes.count("EXECUTED") == 1, outcomes
    assert len([value for value in outcomes if value in {"AGENT_ACTION_ALREADY_EXECUTED", "AGENT_ACTION_NOT_PENDING"}]) == 1
    session.expire_all()
    assert len(movement_audits(session)) == 1
    assert session.get(AgentPendingAction, action_id).status == AgentPendingActionStatus.EXECUTED
    assert session.scalar(select(DispatchOrderDetail).where(
        DispatchOrderDetail.delivery_demand_id == arguments["delivery_demand_id"]
    )).dispatch_order_id == arguments["target_order_id"]


def test_mysql_plan_lock_prevents_stale_approval_during_concurrent_change(client, session, mysql_engine):
    _pending, actor, conversation, plan, _arguments, action = create_move_action(client, session)
    actor_id, action_id, plan_id = actor.id, action.id, plan["id"]
    conversation_id = conversation["id"]
    session.commit()
    locked, release, confirming = Event(), Event(), Event()

    def change_under_real_lock():
        with Session(mysql_engine, expire_on_commit=False) as local:
            model = local.scalar(select(DispatchPlan).where(DispatchPlan.id == plan_id).with_for_update())
            model.version += 1
            local.flush()
            locked.set()
            assert release.wait(timeout=15), "test controller did not release owned plan lock"
            local.commit()

    def confirm_after_lock():
        assert locked.wait(timeout=15)
        with Session(mysql_engine, expire_on_commit=False) as local:
            pending, _registry, _executors = build_pending_service(local)
            local_actor = local.get(User, actor_id)
            confirming.set()
            try:
                asyncio.run(pending.confirm(conversation_id, action_id, local_actor))
                return "UNEXPECTED_EXECUTION"
            except AgentPendingActionError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        change = pool.submit(change_under_real_lock)
        confirm = pool.submit(confirm_after_lock)
        try:
            assert confirming.wait(timeout=15)
            # A bounded observation verifies this real MySQL transaction has
            # not slipped through the held plan row lock.
            assert not confirm.done()
        finally:
            release.set()
        change.result(timeout=30)
        outcome = confirm.result(timeout=30)
    assert outcome == "AGENT_ACTION_SNAPSHOT_CHANGED"
    session.expire_all()
    assert movement_audits(session) == []
    assert session.get(AgentPendingAction, action_id).status == AgentPendingActionStatus.FAILED


def test_mysql_lost_commit_response_recovers_verified_receipt(client, session, monkeypatch):
    pending, actor, conversation, _plan, _arguments, action = create_move_action(client, session)
    failure = RuntimeError("synthetic response loss after real MySQL commit")
    native_refresh = session.refresh

    def lose_refresh(instance, *args, **kwargs):
        if isinstance(instance, AgentPendingAction) and instance.status == AgentPendingActionStatus.EXECUTED:
            raise failure
        return native_refresh(instance, *args, **kwargs)

    monkeypatch.setattr(session, "refresh", lose_refresh)
    with pytest.raises(RuntimeError) as error:
        asyncio.run(pending.confirm(conversation["id"], action.id, actor))
    assert error.value is failure
    recovered = pending.recover_execution(conversation["id"], action.id, actor)
    assert recovered.data["recovery_verified"] is True
    assert recovered.data["original_result_available"] is False
    assert len(movement_audits(session)) == 1


def test_mysql_business_pending_action_resumes_after_service_reconstruction(client, session, mysql_engine, tmp_path):
    initial, actor, conversation, _plan, arguments, action = pending_graph(client, session, tmp_path)
    actor_id, conversation_id, action_id = actor.id, conversation["id"], action.id
    checkpoint = initial.graph_store.path
    assert checkpoint.is_file(), "LangGraph must persist a real owned SQLite checkpoint"
    session.commit()
    with Session(mysql_engine, expire_on_commit=False) as local:
        pending, registry, executors = build_pending_service(local)
        restarted = AgentService(FakeModelClient([]), registry, executors,
                                 pending_action_service=pending, checkpoint_path=checkpoint)
        result = asyncio.run(restarted.resume_action(conversation_id, action_id,
                                                     local.get(User, actor_id), "confirm"))
        assert result["status"] == "executed"
    session.expire_all()
    assert session.get(AgentPendingAction, action_id).status == AgentPendingActionStatus.EXECUTED
    assert len(movement_audits(session)) == 1
    assert session.scalar(select(DispatchOrderDetail).where(
        DispatchOrderDetail.delivery_demand_id == arguments["delivery_demand_id"]
    )).dispatch_order_id == arguments["target_order_id"]


def test_mysql_multiple_threads_have_distinct_checkpoints_and_real_tool_results(client, session, mysql_engine, tmp_path):
    _pending, actor, _conversation, plan, _arguments, _action = create_move_action(client, session)
    conversations = [client.post("/api/v1/agent/conversations").json()["id"] for _ in range(2)]
    actor_id, expected_plan_id = current_admin(session).id, plan["id"]
    session.commit()
    barrier = Barrier(2, timeout=15)

    def execute(conversation_id):
        with Session(mysql_engine, expire_on_commit=False) as local:
            model = ScriptedPlanner({"steps": [step("transport", "list_transport_tasks", {"date": "2026-09-24"})]},
                                    "合成运输任务查询完成。")
            agent = service(local, tmp_path, model)
            local_actor = local.get(User, actor_id)
            barrier.wait()
            result = asyncio.run(agent.chat("查看运输任务", AgentToolContext(
                current_user=local_actor, conversation_id=conversation_id)))
            tool_messages = [message for message in model.messages[-1] if message.role.value == "tool"]
            data = json.loads(tool_messages[0].content)["data"]
            return result.execution, data

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(execute, conversation_id) for conversation_id in conversations]
        results = [future.result(timeout=60) for future in futures]
    reports = [value[0] for value in results]
    assert all(report.status == "COMPLETED" for report in reports)
    assert len({report.execution_id for report in reports}) == 2
    assert {report.conversation_id for report in reports} == set(conversations)
    for _report, data in results:
        assert data["returned_count"] > 0
        assert any(item["plan_id"] == expected_plan_id for item in data["items"])

