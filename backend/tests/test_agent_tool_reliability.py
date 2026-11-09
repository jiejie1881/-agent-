"""Tool boundary/retry checks; real SQL services use only the owned test fixture."""
import asyncio
from datetime import date
from decimal import Decimal
from threading import Event
from time import sleep as thread_sleep
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.agent.exceptions import AgentToolArgumentsError, AgentToolExecutionError
from app.agent.reliability import (
    AgentToolTimeoutError, ErrorCategory, RetryPolicy, classify_failure,
    isolated_read_with_timeout, run_with_retry,
)
from app.agent.schemas.tool import AgentToolDefinition, StrictToolArgs
from app.agent.tool_execution import (
    MAX_TOOL_RESULT_BYTES, AgentToolContext, AgentToolExecutor,
    AgentToolExecutorRegistry, AgentToolResult,
)
from app.agent.tool_registry import AgentToolRegistry
from app.domain.enums import UserRole
from app.domain.exceptions import BusinessError, PermissionDeniedError
from app.domain.permissions import Permission


def actor(role=UserRole.VIEWER, active=True):
    return AgentToolContext(current_user=SimpleNamespace(id=999, role=role, is_active=active))


class NoArguments(StrictToolArgs):
    pass


class ProbeTool(AgentToolExecutor):
    name = 'reliability_probe'
    arguments_type = NoArguments

    def _execute(self, arguments, context):
        return {'count': 0, 'items': []}


def probe_registry(executor=None, permission=Permission.AGENT_READ):
    definition = AgentToolDefinition(name='reliability_probe', description='Owned test probe',
                                     arguments_schema=NoArguments, required_permission=permission)
    registry = AgentToolRegistry([definition])
    return AgentToolExecutorRegistry([executor or ProbeTool()], registry)


@pytest.mark.parametrize('name,payload', [
    ('get_dispatch_plan_detail', {'plan_id': True}),
    ('get_dispatch_plan_detail', {'plan_id': '1'}),
    ('get_dispatch_plan_detail', {'plan_id': 1.0}),
    ('get_vehicle_attendance', {'date': '2026-11-01', 'vehicle_id': False}),
    ('list_delivery_demands', {'date': '2026-11-01', 'store_id': '01'}),
    ('list_delivery_demands', {'date': '2026-11-01', 'offset': '0'}),
    ('list_delivery_demands', {'date': '2026-11-01', 'limit': True}),
    ('search_knowledge_base', {'query': '规则', 'top_k': '4'}),
])
def test_json_integer_contract_rejects_coercion(name, payload):
    with pytest.raises(AgentToolArgumentsError):
        AgentToolRegistry().validate_arguments(name, payload)


def test_integer_guard_preserves_date_enum_and_typed_models():
    registry = AgentToolRegistry()
    result = registry.validate_arguments('list_delivery_demands',
        {'date': '2026-11-01', 'period': 'MORNING', 'store_id': 1, 'offset': 0, 'limit': 1})
    assert result.date == date(2026, 11, 1)
    assert result.period.value == 'MORNING'
    assert registry.validate_arguments('list_delivery_demands', result).store_id == 1
    from app.agent.schemas.tool import GetDispatchPlanDetailArgs
    unsafe = GetDispatchPlanDetailArgs.model_construct(plan_id=True)
    with pytest.raises(AgentToolArgumentsError):
        registry.validate_arguments('get_dispatch_plan_detail', unsafe)


@pytest.mark.parametrize('context', [actor(UserRole.DRIVER), actor(active=False)])
def test_direct_registry_enforces_identity_permissions(context):
    with pytest.raises(PermissionDeniedError):
        asyncio.run(probe_registry().execute('reliability_probe', {}, context))


def test_direct_registry_respects_tool_specific_permission():
    with pytest.raises(PermissionDeniedError):
        asyncio.run(probe_registry(permission=Permission.OPERATIONS_WRITE).execute('reliability_probe', {}, actor()))
    result = asyncio.run(probe_registry().execute('reliability_probe', {}, actor()))
    assert result.data == {'count': 0, 'items': []}


@pytest.mark.parametrize('data', [
    {'value': float('nan')}, {'value': float('inf')},
    {'nested': [{'value': float('-inf')}]}, {'nested': (float('nan'),)},
    {'quantity': Decimal('NaN')}, {'quantity': Decimal('Infinity')},
    {1: 'coercion'}, {'values': {1, 2}},
    {'value': 'x' * MAX_TOOL_RESULT_BYTES},
])
def test_result_json_boundary_rejects_unsafe_or_unbounded_data(data):
    with pytest.raises((ValidationError, ValueError)):
        AgentToolResult.from_data('reliability_probe', data)


def test_result_normalizes_supported_business_scalars():
    result = AgentToolResult.from_data('reliability_probe', {'date': date(2026, 11, 1), 'quantity': Decimal('1.25')})
    assert result.data == {'date': '2026-11-01', 'quantity': '1.25'}


def test_registry_rejects_wrong_tool_envelope():
    class WrongTool(ProbeTool):
        async def execute(self, arguments, context):
            return AgentToolResult.from_data('different_tool', {})
    with pytest.raises(AgentToolExecutionError):
        asyncio.run(probe_registry(WrongTool()).execute('reliability_probe', {}, actor()))


def test_registry_rejects_raw_result_instead_of_envelope():
    class RawTool(ProbeTool):
        async def execute(self, arguments, context):
            return {'items': []}
    with pytest.raises(AgentToolExecutionError):
        asyncio.run(probe_registry(RawTool()).execute('reliability_probe', {}, actor()))


def transient_database_failure():
    return OperationalError('redacted', {}, Exception(1213, 'not exposed'))


def test_classifier_reads_safe_database_cause_not_exception_message():
    try:
        raise transient_database_failure()
    except OperationalError as exc:
        wrapped = AgentToolExecutionError('reliability_probe')
        wrapped.__cause__ = exc
    failure = classify_failure(wrapped)
    assert failure.category == ErrorCategory.DATABASE and failure.retryable
    assert failure.code == 'AGENT_DATABASE_TEMPORARY'
    denied = PermissionDeniedError()
    denied.__cause__ = wrapped
    assert classify_failure(denied).category == ErrorCategory.PERMISSION
    assert not classify_failure(denied).retryable


@pytest.mark.parametrize('code', [
    'AGENT_STATE_MISMATCH', 'AGENT_STATE_VERSION', 'AGENT_CHECKPOINT_MISSING',
    'AGENT_RECOVERY_NOT_ALLOWED', 'AGENT_WRITE_STATE_UNCERTAIN', 'AGENT_ACTION_RECOVERY_UNVERIFIED',
])
def test_state_recovery_failures_have_explicit_non_retryable_category(code):
    failure = classify_failure(BusinessError('do not expose raw state', 409, code))
    assert failure.category == ErrorCategory.STATE_RECOVERY
    assert failure.code == code and not failure.retryable


def test_retry_is_bounded_exponential_and_preserves_event_metadata():
    async def exercise():
        calls, waits, events = [], [], []
        async def operation():
            calls.append(1)
            if len(calls) < 3:
                raise transient_database_failure()
            return 'ok'
        async def wait(value):
            waits.append(value)
        result = await run_with_retry(operation, read_only=True,
            policy=RetryPolicy(max_attempts=3), sleep=wait,
            on_retry=lambda attempt, failure, delay: events.append((attempt, failure.code, delay)))
        assert result == 'ok' and len(calls) == 3
        assert waits == [.05, .1]
        assert events == [(1, 'AGENT_DATABASE_TEMPORARY', .05), (2, 'AGENT_DATABASE_TEMPORARY', .1)]
    asyncio.run(exercise())


@pytest.mark.parametrize('error', [PermissionDeniedError(), AgentToolArgumentsError('probe'),
    BusinessError('business rule'), AgentToolTimeoutError()])
def test_retry_never_retries_security_business_parameters_or_soft_timeout(error):
    async def exercise():
        calls = []
        async def operation():
            calls.append(1)
            raise error
        with pytest.raises(type(error)):
            await run_with_retry(operation, read_only=True)
        assert len(calls) == 1
    asyncio.run(exercise())


def test_retry_never_replays_write_or_exceeds_wait_budget():
    async def exercise(read_only, policy):
        calls = []
        async def operation():
            calls.append(1)
            raise transient_database_failure()
        with pytest.raises(OperationalError):
            await run_with_retry(operation, read_only=read_only, policy=policy)
        assert len(calls) == 1
    asyncio.run(exercise(False, RetryPolicy()))
    asyncio.run(exercise(True, RetryPolicy(max_total_wait_seconds=0)))


def test_soft_timeout_drains_worker_before_returning_error():
    ended = Event()
    def read():
        thread_sleep(.03)
        ended.set()
        return 'finished'
    async def exercise():
        with pytest.raises(AgentToolTimeoutError):
            await isolated_read_with_timeout(read, timeout_seconds=.001)
        assert ended.is_set()
    asyncio.run(exercise())


def test_cancelled_read_drains_before_propagating_cancellation():
    started, ended = Event(), Event()
    def read():
        started.set()
        thread_sleep(.03)
        ended.set()
    async def exercise():
        task = asyncio.create_task(isolated_read_with_timeout(read, timeout_seconds=1))
        while not started.is_set():
            await asyncio.sleep(.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert ended.is_set()
    asyncio.run(exercise())


def test_real_business_tool_data_preserved_under_reliability_boundary(client, session):
    from tests.test_agent_dispatch_foundation import DAY, resources
    from tests.test_agent_phase2 import current_admin
    from app.api.agent_dependencies import build_task_registry
    from app.domain.enums import DeliveryDemandStatus
    seeded = resources.__wrapped__(session)
    _, tools = build_task_registry(session)
    result = asyncio.run(tools.execute('list_delivery_demands', {'date': DAY.isoformat()},
        AgentToolContext(current_user=current_admin(session))))
    assert result.tool_name == 'list_delivery_demands'
    assert result.data['items'][0]['id'] == seeded['demand'].id
    assert seeded['demand'].status == DeliveryDemandStatus.PENDING
