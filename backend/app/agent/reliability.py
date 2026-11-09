"""Conservative reliability primitives; no model, database or network access.

Retries are only appropriate for a caller that creates a fresh read-only
session on every attempt.  A Python thread cannot be killed safely: the
timeout below is a *soft* deadline that drains its isolated worker before
returning an error, so a retry can never overlap the original operation.
"""
from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

from sqlalchemy.exc import DBAPIError, DisconnectionError, IntegrityError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as DatabasePoolTimeout
from sqlalchemy.orm.exc import StaleDataError

from app.agent.exceptions import (
    AgentModelError,
    AgentToolArgumentsError,
    AgentToolError,
    AgentToolNotFoundError,
)
from app.domain.exceptions import BusinessError, PermissionDeniedError

T = TypeVar('T')


class ErrorCategory(str, Enum):
    PARAMETERS = 'PARAMETERS'
    PERMISSION = 'PERMISSION'
    BUSINESS_RULE = 'BUSINESS_RULE'
    DATABASE = 'DATABASE'
    MODEL = 'MODEL'
    TOOL_TIMEOUT = 'TOOL_TIMEOUT'
    CONNECTION = 'CONNECTION'
    CONCURRENCY = 'CONCURRENCY'
    STATE_RECOVERY = 'STATE_RECOVERY'
    CANCELLED = 'CANCELLED'
    INTERNAL = 'INTERNAL'


@dataclass(frozen=True)
class FailureInfo:
    category: ErrorCategory
    code: str
    retryable: bool = False


class AgentToolTimeoutError(BusinessError):
    def __init__(self) -> None:
        super().__init__('只读工具超过等待时限，已等待独立执行器结束；请人工检查后重试',
                         status_code=504, code='AGENT_TOOL_TIMEOUT')


def _causes(exc: BaseException) -> tuple[BaseException, ...]:
    values = []
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        values.append(exc)
        exc = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
    return tuple(values)


def classify_failure(exc: BaseException) -> FailureInfo:
    """Return safe metadata, never provider/SQL text or parameters.

    Security and domain decisions take precedence over nested infrastructure
    errors.  An AgentToolError wrapper is intentionally transparent so its
    original SQLAlchemy cause remains classifiable.
    """
    chain = _causes(exc)
    from app.agent.execution_control import ExecutionDeadlineError
    if any(isinstance(e, ExecutionDeadlineError) for e in chain):
        return FailureInfo(ErrorCategory.TOOL_TIMEOUT, 'AGENT_EXECUTION_DEADLINE')
    if any(isinstance(e, asyncio.CancelledError) for e in chain):
        return FailureInfo(ErrorCategory.CANCELLED, 'AGENT_CANCELLED')
    if any(isinstance(e, (PermissionDeniedError, PermissionError)) for e in chain):
        return FailureInfo(ErrorCategory.PERMISSION, 'FORBIDDEN')
    if any(isinstance(e, AgentToolNotFoundError) for e in chain):
        return FailureInfo(ErrorCategory.PARAMETERS, 'AGENT_TOOL_NOT_FOUND')
    if any(isinstance(e, AgentToolArgumentsError) for e in chain):
        return FailureInfo(ErrorCategory.PARAMETERS, 'AGENT_TOOL_ARGUMENTS_ERROR')
    if any(isinstance(e, AgentToolTimeoutError) for e in chain):
        return FailureInfo(ErrorCategory.TOOL_TIMEOUT, 'AGENT_TOOL_TIMEOUT')
    if any(isinstance(e, AgentModelError) for e in chain):
        return FailureInfo(ErrorCategory.MODEL, 'AGENT_MODEL_ERROR')
    recovery_codes = {
        'AGENT_STATE_MISMATCH', 'AGENT_STATE_VERSION', 'AGENT_CHECKPOINT_MISSING',
        'AGENT_RECOVERY_NOT_ALLOWED', 'AGENT_WRITE_STATE_UNCERTAIN',
        'AGENT_ACTION_RECOVERY_UNVERIFIED',
    }
    for error in chain:
        if isinstance(error, BusinessError) and error.code in recovery_codes:
            return FailureInfo(ErrorCategory.STATE_RECOVERY, error.code)
    for error in chain:
        if isinstance(error, BusinessError) and not isinstance(error, AgentToolError):
            if error.status_code == 409:
                return FailureInfo(ErrorCategory.CONCURRENCY, 'AGENT_BUSINESS_CONFLICT')
            return FailureInfo(ErrorCategory.BUSINESS_RULE, 'AGENT_BUSINESS_RULE')
    if any(isinstance(e, (IntegrityError, StaleDataError)) for e in chain):
        return FailureInfo(ErrorCategory.CONCURRENCY, 'AGENT_DATABASE_CONFLICT')
    for error in chain:
        if isinstance(error, (DatabasePoolTimeout, DisconnectionError)):
            return FailureInfo(ErrorCategory.DATABASE, 'AGENT_DATABASE_TEMPORARY', True)
        if isinstance(error, DBAPIError):
            original = error.orig
            arguments = getattr(original, 'args', ())
            mysql_number = arguments[0] if arguments and type(arguments[0]) is int else None
            sqlite_number = getattr(original, 'sqlite_errorcode', None)
            temporary = bool(error.connection_invalidated or mysql_number in {1205, 1213, 2006, 2013}
                             or sqlite_number in {5, 6})
            return FailureInfo(ErrorCategory.DATABASE,
                               'AGENT_DATABASE_TEMPORARY' if temporary else 'AGENT_DATABASE_ERROR', temporary)
    if any(isinstance(e, SQLAlchemyError) for e in chain):
        return FailureInfo(ErrorCategory.DATABASE, 'AGENT_DATABASE_ERROR')
    if any(isinstance(e, ConnectionError) for e in chain):
        return FailureInfo(ErrorCategory.CONNECTION, 'AGENT_TOOL_CONNECTION', True)
    if any(isinstance(e, TimeoutError) for e in chain):
        return FailureInfo(ErrorCategory.TOOL_TIMEOUT, 'AGENT_TOOL_TIMEOUT')
    if any(isinstance(e, (TypeError, ValueError, KeyError, IndexError)) for e in chain):
        return FailureInfo(ErrorCategory.PARAMETERS, 'AGENT_INVALID_RESULT_OR_ARGUMENT')
    return FailureInfo(ErrorCategory.INTERNAL, 'AGENT_TOOL_INTERNAL')


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2
    base_delay_seconds: float = .05
    max_delay_seconds: float = .25
    max_total_wait_seconds: float = .5

    def __post_init__(self) -> None:
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 3:
            raise ValueError('max_attempts must be in [1, 3]')
        for value in (self.base_delay_seconds, self.max_delay_seconds, self.max_total_wait_seconds):
            if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 30:
                raise ValueError('retry waits must be finite and in [0, 30] seconds')
        if self.base_delay_seconds > self.max_delay_seconds:
            raise ValueError('base retry wait exceeds maximum wait')


async def run_with_retry(
    operation: Callable[[], Awaitable[T]], *, read_only: bool,
    policy: RetryPolicy | None = None,
    on_retry: Callable[[int, FailureInfo, float], None] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Bounded retries for known temporary failures of isolated reads only."""
    policy = policy or RetryPolicy()
    waited = 0.0
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return await operation()
        except Exception as exc:
            failure = classify_failure(exc)
            delay = min(policy.base_delay_seconds * (2 ** (attempt - 1)), policy.max_delay_seconds)
            if (not read_only or not failure.retryable or attempt >= policy.max_attempts
                    or waited + delay > policy.max_total_wait_seconds):
                raise
            if on_retry is not None:
                on_retry(attempt, failure, delay)
            await sleep(delay)
            waited += delay
    raise AssertionError('bounded retry loop exhausted without a result')


async def _drain(worker: asyncio.Task) -> None:
    # Even cancellation must not leave a DB thread operating behind the next
    # request. Repeated cancellation is deferred until the worker has finished.
    while not worker.done():
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    if worker.done() and not worker.cancelled():
        worker.exception()  # Retrieve a possible failure; preserve it as cause at the caller.


async def isolated_read_with_timeout(operation: Callable[[], T], *, timeout_seconds: float) -> T:
    """Soft timeout for a fresh-session read worker; never use for writes.

    The caller must prove operation is read-only and owns all of its resources.
    If operation never returns, draining also cannot finish. This is explicitly
    not a hard database/statement cancellation mechanism.
    """
    if type(timeout_seconds) not in {int, float} or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError('timeout_seconds must be finite and positive')
    worker = asyncio.create_task(asyncio.to_thread(operation))
    try:
        done, _ = await asyncio.wait({worker}, timeout=timeout_seconds)
        if done:
            return worker.result()
        await _drain(worker)
        cause = None if worker.cancelled() else worker.exception()
        raise AgentToolTimeoutError() from cause
    except asyncio.CancelledError:
        await _drain(worker)
        raise
