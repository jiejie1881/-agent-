"""Explicit cancellation boundaries; never equate thread cancellation with termination."""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from enum import Enum
from time import monotonic
from typing import Awaitable, Callable, TypeVar

from app.domain.exceptions import BusinessError

T = TypeVar('T')


class Boundary(str, Enum):
    COOPERATIVE_ASYNC = 'COOPERATIVE_ASYNC'
    OWNED_LEAF_PROCESS = 'OWNED_LEAF_PROCESS'
    THREAD_DRAIN_ONLY = 'THREAD_DRAIN_ONLY'
    TRANSACTION_RECONCILIATION = 'TRANSACTION_RECONCILIATION'
    UNVERIFIED = 'UNVERIFIED'


@dataclass(frozen=True)
class ToolControlContract:
    tool: str
    boundary: Boundary
    timeout_seconds: float
    side_effects: bool = False
    retry_safe: bool = False

    def __post_init__(self):
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError('A finite positive timeout is required')
        if self.side_effects and self.retry_safe:
            raise ValueError('Side effects cannot be automatically replayed')


class ExecutionDeadlineError(BusinessError):
    def __init__(self):
        super().__init__('执行时限已到，停止接收后续结果；底层取消能力以执行边界为准',
                         status_code=504, code='AGENT_EXECUTION_DEADLINE')


class ExecutionControl:
    """Parent cancellation scope. Acknowledgement follows owned-task draining.

    Cooperative cancellation is NOT a promise to kill arbitrary synchronous
    calls or coroutine code that suppresses cancellation. Such calls must run
    in a separately attested process boundary or remain explicitly partial.
    """
    def __init__(self, seconds: float, cancellation_requested: Callable[[], bool] = lambda: False):
        if type(seconds) not in {int, float} or not math.isfinite(seconds) or not 0 < seconds <= 3600:
            raise ValueError('deadline must be finite and in (0,3600]')
        self.deadline = monotonic() + seconds
        self.cancellation_requested = cancellation_requested
        self.cancelled = False
        self.expired = False
        self.children: set[asyncio.Task] = set()

    def checkpoint(self):
        if self.cancelled or self.cancellation_requested():
            self.cancelled = True
            raise asyncio.CancelledError()
        if self.expired or monotonic() >= self.deadline:
            self.expired = True
            raise ExecutionDeadlineError()

    async def _drain(self):
        children = tuple(self.children)
        for child in children:
            if not child.done():child.cancel()
        collector = asyncio.gather(*children, return_exceptions=True)
        while not collector.done():
            try:await asyncio.shield(collector)
            except asyncio.CancelledError:continue
        collector.result()

    async def run(self, operation: Callable[[], Awaitable[T]]) -> T:
        self.checkpoint()
        child = asyncio.create_task(operation())
        self.children.add(child)
        try:
            while not child.done():
                await asyncio.wait({child}, timeout=min(.05, max(.001, self.deadline-monotonic())))
                self.checkpoint()
            self.checkpoint()
            return child.result()
        except BaseException:
            await self._drain()
            raise
        finally:
            self.children.discard(child)


async def run_owned_leaf_process(argv: tuple[str, ...], *, timeout_seconds: float,
                                 cancelled: Callable[[], bool] = lambda: False) -> tuple[int, bytes, bytes]:
    """Internal adapter for reviewed leaf workers only, never model-supplied commands.

    No shell and no inherited stdin. The registered worker must not spawn
    descendants. Arbitrary process trees, shared DB connections and committed
    business effects are outside this adapter's termination guarantee.
    """
    if not argv or type(timeout_seconds) not in {int,float} or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError('Invalid owned process contract')
    proc = await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    reader = asyncio.create_task(proc.communicate(input=b''))
    control = ExecutionControl(timeout_seconds, cancelled)
    try:
        async def result():return await asyncio.shield(reader)
        out, err = await control.run(result)
        return proc.returncode, out, err
    finally:
        # A terminated leaf cannot emit a late result. Always reap its actual
        # process and drain pipes before returning or propagating cancellation.
        if proc.returncode is None:
            proc.kill()
        while not reader.done():
            try:await asyncio.shield(reader)
            except asyncio.CancelledError:continue
        reader.result()
        await proc.wait()
