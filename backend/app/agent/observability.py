"""Optional metadata-only Agent traces. Raw business values never enter the queue."""
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
from queue import Empty, Full, Queue
from threading import Lock, Thread
from time import monotonic
from uuid import UUID

from langchain_core.callbacks.base import BaseCallbackHandler
from langsmith.run_helpers import tracing_context

from app.core.config import get_settings

_active = ContextVar('safe_agent_observer', default=None)
_senders = {}
_senders_lock = Lock()
_NODES = frozenset({
    # Fixed server-owned task graph names; never admit dynamic/user labels.
    'intent', 'planner', 'validate_plan', 'analyze', 'decide', 'replan', 'finish',
    'list_vehicles', 'list_drivers', 'list_transport_tasks', 'analyze_capacity',
    'preview_dispatch_candidate', 'get_daily_exceptions', 'list_exception_cases',
    'LangGraph', 'model', 'tools', 'approval', 'execute',
    'load_dispatch_context', 'prepare_dispatch_generation', 'prepare_dispatch_revision',
    'generate_dispatch_candidate', 'revise_dispatch_candidate', 'validate_dispatch_candidate',
    'build_shadow_result', 'build_rejected_result', 'build_blocked_result',
    'list_delivery_demands', 'get_vehicle_attendance', 'list_dispatch_plans',
    'get_dispatch_plan_detail', 'get_unassigned_demands', 'validate_dispatch_plan',
    'search_knowledge_base', 'move_delivery_demand', 'cancel_dispatch_plan',
})


def _safe_metadata(metadata):
    allowed = {
        'environment': ('development', 'test'), 'workflow': ('chat', 'resume', 'dispatch'),
        'trace_schema': (1,), 'business_status': ('SUCCESS', 'REJECTED', 'BLOCKED'),
    }
    return {key: value for key, value in metadata.items()
            if key in allowed and isinstance(value, (str, int)) and value in allowed[key]}


def _make_client(settings):
    from langsmith import Client
    from urllib3.util.retry import Retry
    return Client(
        api_urls={settings.langsmith_endpoint: settings.langsmith_api_key.get_secret_value()},
        timeout_ms=(2000, 5000), retry_config=Retry(total=0),
        auto_batch_tracing=False, hide_inputs=True, hide_outputs=True,
        hide_metadata=_safe_metadata,
        omit_traced_runtime_info=True,
    )


class TraceSender:
    """Bounded best-effort worker. Never blocks Agent completion on external I/O."""
    def __init__(self, factory, *, capacity=256):
        self.factory = factory
        self.queue = Queue(maxsize=capacity)
        self.dropped = 0
        self.failed = 0
        self.sent = 0
        self.last_failure_type = None
        self.last_root_id = None
        self._thread = None
        self._lock = Lock()
        self._closed = False

    def submit(self, operation, payload):
        with self._lock:
            if self._closed:
                self.dropped += 1
                return
            if (operation == 'create' and isinstance(payload.get('id'), UUID)
                    and payload['id'] == payload.get('trace_id')):
                self.last_root_id = payload['id']
            try:
                self.queue.put_nowait((operation, payload))
            except Full:
                self.dropped += 1
                return
            if self._thread is None:
                self._thread = Thread(target=self._worker, name='safe-agent-traces', daemon=True)
                self._thread.start()

    def _worker(self):
        client = None
        try:
            while True:
                try:
                    operation, payload = self.queue.get(timeout=0.1)
                except Empty:
                    if self._closed:
                        return
                    continue
                try:
                    if client is None:
                        client = self.factory()
                    if operation == 'create':
                        client.create_run(**payload)
                    else:
                        client.update_run(**payload)
                    self.sent += 1
                except Exception as error:  # noqa: BLE001 -- exporter failures must never replay business work.
                    # No exception text, credentials, business retry, or write compensation.
                    self.failed += 1
                    self.last_failure_type = type(error).__name__
                finally:
                    self.queue.task_done()
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:  # noqa: BLE001 -- even SDK cleanup is optional telemetry.
                    self.failed += 1

    def flush(self, timeout=3):
        """Explicit test/CLI helper only; not used in the business request path."""
        from time import sleep
        deadline = monotonic() + timeout
        while self.queue.unfinished_tasks and monotonic() < deadline:
            sleep(0.005)
        return not self.queue.unfinished_tasks

    def close(self):
        self._closed = True
        if self._thread:
            self._thread.join(timeout=2)


def _sender(settings):
    import re
    key = settings.langsmith_api_key
    if (not settings.langsmith_tracing or settings.app_environment == 'production'
            or key is None or not key.get_secret_value().strip()
            or re.fullmatch(r'logistics-agent-(dev|test)(-[a-z0-9-]{1,40})?', settings.langsmith_project) is None
            or settings.langsmith_endpoint not in {
                'https://api.smith.langchain.com', 'https://eu.api.smith.langchain.com',
            }):
        return None
    # Use a fingerprint as cache key; never expose credential values in diagnostics.
    import hashlib
    identity = (settings.langsmith_endpoint, settings.langsmith_project,
                hashlib.sha256(key.get_secret_value().encode()).hexdigest())
    with _senders_lock:
        if identity not in _senders:
            if len(_senders) >= 4:
                return None
            _senders[identity] = TraceSender(lambda: _make_client(settings))
        return _senders[identity]


class SafeAgentCallback(BaseCallbackHandler):
    raise_error = False
    run_inline = True

    def __init__(self, sender, project, environment, workflow):
        self.sender, self.project = sender, project
        self.metadata = {'environment': environment, 'workflow': workflow, 'trace_schema': 1}
        self._runs = {}
        self._lock = Lock()

    def _start(self, kind, run_id, parent_run_id, name):
        if not isinstance(run_id, UUID):
            return
        now = datetime.now(UTC)
        safe_name = name if isinstance(name, str) and name in _NODES else kind
        with self._lock:
            parent = self._runs.get(parent_run_id)
            trace_id = parent[0] if parent else run_id
            stamp = now.strftime('%Y%m%dT%H%M%S%fZ') + str(run_id)
            dotted = parent[1] + '.' + stamp if parent else stamp
            self._runs[run_id] = (trace_id, dotted, parent_run_id if parent else None, safe_name, kind, now)
        payload = {'id': run_id, 'name': safe_name, 'run_type': kind,
                   'inputs': {}, 'start_time': now, 'project_name': self.project,
                   'trace_id': trace_id, 'dotted_order': dotted,
                   'extra': {'metadata': dict(self.metadata)}}
        if parent:
            payload['parent_run_id'] = parent_run_id
        self.sender.submit('create', payload)

    def _end(self, run_id, failed=False, outputs=None):
        with self._lock:
            known = self._runs.get(run_id)
        if known:
            metadata = dict(self.metadata)
            if (isinstance(outputs, dict) and isinstance(outputs.get('status'), str)
                    and outputs['status'] in {'SUCCESS', 'REJECTED', 'BLOCKED'}):
                metadata['business_status'] = outputs['status']
            self.sender.submit('update', {'run_id': run_id, 'end_time': datetime.now(UTC),
                'trace_id': known[0], 'dotted_order': known[1],
                'parent_run_id': known[2], 'name': known[3], 'run_type': known[4],
                'start_time': known[5], 'session_name': self.project,
                'extra': {'metadata': metadata},
                'error': 'agent_execution_error' if failed else None, 'outputs': {}})

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
        self._start('chain', run_id, parent_run_id, kwargs.get('name'))

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        self._end(run_id, outputs=outputs)

    def on_chain_error(self, error, *, run_id, **kwargs):
        self._end(run_id, True)

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
        self._start('llm', run_id, parent_run_id, 'model')

    def on_llm_end(self, response, *, run_id, **kwargs):
        self._end(run_id)

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._end(run_id, True)

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kwargs):
        # Ignore serialized tool descriptions, args and any externally supplied names.
        self._start('tool', run_id, parent_run_id, (serialized or {}).get('name'))

    def on_tool_end(self, output, *, run_id, **kwargs):
        self._end(run_id)

    def on_tool_error(self, error, *, run_id, **kwargs):
        self._end(run_id, True)


def trace_config(config):
    result = dict(config)
    observer = _active.get()
    if observer is not None:
        result['callbacks'] = [observer]
    return result


def observed_agent(workflow):
    def decorate(fn):
        @wraps(fn)
        async def wrapped(self, *args, **kwargs):
            settings = getattr(self, 'settings', None) or get_settings()
            try:
                sender = _sender(settings)
                observer = SafeAgentCallback(sender, settings.langsmith_project,
                    settings.app_environment, workflow) if sender else None
            except Exception:  # noqa: BLE001 -- optional observer setup must fail open for business.
                observer = None
            token = _active.set(observer)
            try:
                # Native automatic tracing would serialize raw graph states.
                with tracing_context(enabled=False, parent=False):
                    return await fn(self, *args, **kwargs)
            finally:
                _active.reset(token)
        return wrapped
    return decorate


def no_automatic_trace(fn):
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        with tracing_context(enabled=False, parent=False):
            return await fn(*args, **kwargs)
    return wrapped
