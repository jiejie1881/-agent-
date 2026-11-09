"""Shared fail-closed model egress budget. No initialization during import/startup.

This is a NEW ledger format. Never migrate/open the protected manual ledger.
Initialization is an explicit offline operation; callers only open existing files.
Money is a conservative reservation, not a claim of provider invoice accuracy.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

import httpx


class BudgetDenied(RuntimeError):
    def __init__(self, reason="budget_unavailable"):
        self.reason = reason
        super().__init__("模型预算保护未通过，本次不允许外发。")


@dataclass(frozen=True)
class BudgetPolicy:
    max_calls: int
    max_micro_cny: int
    reserve_micro_cny: int
    max_inflight: int = 1
    max_input_bytes: int = 24000
    max_output_tokens: int = 2048

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in asdict(self).values()):
            raise BudgetDenied("invalid_policy")
        if self.reserve_micro_cny > self.max_micro_cny:
            raise BudgetDenied("reservation_exceeds_budget")

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


class ModelBudget:
    FILENAME = "model-budget-v1.sqlite3"
    SCHEMA = {
        "gate": "CREATE TABLE gate(id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL, policy TEXT NOT NULL, expires REAL NOT NULL, stopped INTEGER NOT NULL CHECK(stopped IN (0,1)))",
        "calls": "CREATE TABLE calls(operation_id TEXT PRIMARY KEY, digest TEXT NOT NULL, purpose TEXT NOT NULL, reserved INTEGER NOT NULL CHECK(reserved>0), status TEXT NOT NULL, started REAL NOT NULL, finished REAL)",
    }

    def __init__(self, path, policy):
        self.path, self.policy = Path(path).absolute(), policy
        if self.path.name != self.FILENAME:
            raise BudgetDenied("not_new_ledger_format_path")

    def _reject_sealed_evidence(self):
        # Sealed reports are immutable even when they contain a dedicated test
        # budget. Never open SQLite, refresh quotas or settle calls there.
        # No manifest contents or credentials are read to make this decision.
        for parent in self.path.parents:
            try:
                (parent / "SHA256_MANIFEST.json").lstat()
            except FileNotFoundError:
                continue
            except OSError:
                raise BudgetDenied("evidence_boundary_unverifiable") from None
            raise BudgetDenied("sealed_evidence_budget")

    def _check_path(self):
        self._reject_sealed_evidence()
        for part in (self.path, *self.path.parents):
            if part.is_symlink() or (part.exists() and getattr(part.lstat(), "st_file_attributes", 0) & 0x400):
                raise BudgetDenied("ledger_link_or_reparse")
        if not self.path.is_file():
            raise BudgetDenied("ledger_missing_no_auto_create")
        if self.path.stat().st_nlink != 1:
            raise BudgetDenied("ledger_hardlink")

    def initialize_new(self, *, expires_at):
        """Explicit synthetic/offline provisioning only; never called by clients."""
        self._reject_sealed_evidence()
        if not math.isfinite(expires_at) or expires_at <= time.time():
            raise BudgetDenied("invalid_expiry")
        for part in self.path.parents:
            if part.is_symlink() or (part.exists() and getattr(part.lstat(), "st_file_attributes", 0) & 0x400):
                raise BudgetDenied("ledger_link_or_reparse")
        # Exclusive create before SQLite, no overwrite or implicit mkdir.
        with self.path.open("xb"):
            pass
        try:
            with self._connection() as db:
                for definition in self.SCHEMA.values():
                    db.execute(definition)
                db.execute("INSERT INTO gate VALUES(1,1,?,?,0)", (self.policy.fingerprint, expires_at))
        except BaseException:
            # Keep failed initialization evidence; never delete/reinitialize it.
            raise

    @contextmanager
    def _connection(self):
        self._check_path()
        try:
            db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=2)
            try:
                with db:
                    yield db
            finally:
                db.close()
        except sqlite3.Error:
            raise BudgetDenied("ledger_error") from None

    def _validate(self, db, *, active=True):
        schema = dict(db.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"))
        if schema != self.SCHEMA:
            raise BudgetDenied("ledger_schema_untrusted")
        invalid = db.execute("SELECT COUNT(*) FROM calls WHERE typeof(reserved)!='integer' OR reserved<=0 OR status NOT IN ('IN_FLIGHT','HTTP_SUCCEEDED','FAILED_OR_UNKNOWN') OR operation_id IS NULL").fetchone()[0]
        if invalid:
            raise BudgetDenied("ledger_call_state_invalid")
        gate_columns = [row[1] for row in db.execute("PRAGMA table_info(gate)")]
        calls_columns = [row[1] for row in db.execute("PRAGMA table_info(calls)")]
        if (gate_columns != ["id", "version", "policy", "expires", "stopped"]
                or calls_columns != ["operation_id", "digest", "purpose", "reserved", "status", "started", "finished"]
                or db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type IN ('trigger','view')").fetchone()[0]):
            raise BudgetDenied("ledger_schema_untrusted")
        rows = db.execute("SELECT id,version,policy,expires,stopped FROM gate").fetchall()
        if len(rows) != 1 or rows[0][:3] != (1, 1, self.policy.fingerprint):
            raise BudgetDenied("ledger_policy_mismatch")
        expires, stopped = rows[0][3:]
        if type(expires) not in (int, float) or not math.isfinite(expires) or type(stopped) is not int or stopped not in (0, 1):
            raise BudgetDenied("ledger_control_invalid")
        if active and (stopped or time.time() >= expires):
            raise BudgetDenied("ledger_stopped_or_expired")

    def reserve(self, operation_id, digest, purpose):
        if not isinstance(operation_id, str) or not 8 <= len(operation_id) <= 200:
            raise BudgetDenied("operation_id_required")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate(db)
            previous = db.execute("SELECT digest,status FROM calls WHERE operation_id=?", (operation_id,)).fetchone()
            if previous:
                raise BudgetDenied("duplicate_operation" if previous[0] == digest else "operation_payload_conflict")
            count, amount, inflight = db.execute("SELECT COUNT(*),COALESCE(SUM(reserved),0),COALESCE(SUM(status='IN_FLIGHT'),0) FROM calls").fetchone()
            if count >= self.policy.max_calls or amount + self.policy.reserve_micro_cny > self.policy.max_micro_cny:
                raise BudgetDenied("quota_exhausted")
            if inflight >= self.policy.max_inflight:
                raise BudgetDenied("concurrency_exhausted")
            db.execute("INSERT INTO calls VALUES(?,?,?,?,?,?,NULL)",
                       (operation_id, digest, purpose, self.policy.reserve_micro_cny, "IN_FLIGHT", time.time()))

    def finish(self, operation_id, success):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate(db, active=False)
            row = db.execute("UPDATE calls SET status=?,finished=? WHERE operation_id=? AND status='IN_FLIGHT'",
                             ("HTTP_SUCCEEDED" if success else "FAILED_OR_UNKNOWN", time.time(), operation_id))
            if row.rowcount != 1:
                raise BudgetDenied("settlement_not_inflight")
            if not success:
                db.execute("UPDATE gate SET stopped=1 WHERE id=1")


_override = ContextVar("explicit_model_budget", default=None)


@contextmanager
def budget_context(budget):
    """Explicit dependency override for isolated tests, never environment detection."""
    token = _override.set(budget)
    try:
        yield
    finally:
        _override.reset(token)


def budget_for(settings):
    injected = _override.get()
    if injected is not None:
        return injected
    if not settings.model_budget_enabled:
        raise BudgetDenied("model_egress_disabled")
    values = (settings.model_budget_max_calls, settings.model_budget_max_micro_cny,
              settings.model_budget_reserve_micro_cny)
    if not settings.model_budget_path or any(value is None for value in values):
        raise BudgetDenied("budget_configuration_incomplete")
    policy = BudgetPolicy(*values, max_inflight=settings.model_budget_max_inflight,
                          max_input_bytes=settings.model_budget_max_input_bytes,
                          max_output_tokens=settings.model_budget_max_output_tokens)
    return ModelBudget(settings.model_budget_path, policy)


def _prepare(request, budget, endpoint, purpose):
    if request.method != "POST" or str(request.url) != endpoint:
        raise BudgetDenied("unexpected_egress_target")
    if len(request.content) > budget.policy.max_input_bytes:
        raise BudgetDenied("input_limit")
    try:
        payload = json.loads(request.content)
        if not isinstance(payload, dict):
            raise BudgetDenied("invalid_request_payload")
        if purpose in {"chat", "chat_stream"}:
            if (payload.get("stream", False) and purpose != 'chat_stream') or payload.get("n", 1) != 1:
                raise BudgetDenied("unsupported_stream_or_multiple_outputs")
            # Force a provider output cap even when a caller passes None.
            cap = payload.get("max_tokens", payload.get("max_completion_tokens", budget.policy.max_output_tokens))
            if type(cap) is not int or cap <= 0:
                raise BudgetDenied("invalid_output_cap")
            payload.pop("max_completion_tokens", None)
            payload["max_tokens"] = min(cap, budget.policy.max_output_tokens)
        encoded = json.dumps(payload, ensure_ascii=False).encode()
        if len(encoded) > budget.policy.max_input_bytes:
            raise BudgetDenied("input_limit")
    except (ValueError, TypeError):
        raise BudgetDenied("invalid_request_payload") from None
    headers = dict(request.headers)
    headers.pop("content-length", None)
    outgoing = httpx.Request("POST", request.url, headers=headers, content=encoded, extensions=request.extensions)
    request_digest = hashlib.sha256((endpoint + "\n" + purpose).encode() + encoded).hexdigest()
    return outgoing, request_digest


class BudgetedAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self, budget, endpoint, purpose, upstream=None, operation_id=None):
        self.budget, self.endpoint, self.purpose = budget, endpoint, purpose
        if upstream is not None and type(upstream) is not httpx.MockTransport:
            raise BudgetDenied("unapproved_custom_transport")
        if upstream is None and (not isinstance(operation_id, str) or not 8 <= len(operation_id) <= 200 or not operation_id.strip()):
            raise BudgetDenied("stable_operation_id_required")
        self.upstream = upstream or httpx.AsyncHTTPTransport(retries=0)
        self.operation_id = operation_id or uuid4().hex

    async def handle_async_request(self, request):
        outgoing, request_digest = _prepare(request, self.budget, self.endpoint, self.purpose)
        self.budget.reserve(self.operation_id, request_digest, self.purpose)
        try:
            response = await self.upstream.handle_async_request(outgoing)
            if self.purpose == 'chat_stream':
                return httpx.Response(response.status_code, headers=response.headers,
                    stream=_BudgetStream(response, self.budget, self.operation_id), request=request)
            body = await response.aread()
        except BaseException:
            try:
                self.budget.finish(self.operation_id, False)
            except BudgetDenied:
                pass  # Preserve upstream/cancellation error; IN_FLIGHT stays blocking.
            raise
        self.budget.finish(self.operation_id, 200 <= response.status_code < 300)
        return httpx.Response(response.status_code, headers=response.headers, content=body, request=request)

    async def aclose(self):
        await self.upstream.aclose()


class _BudgetStream(httpx.AsyncByteStream):
    def __init__(self, response, budget, operation_id):
        self.response, self.budget, self.operation_id = response, budget, operation_id
        self.finished = False
        self.done_marker = False
        self.tail = b''

    def settle(self, success):
        if not self.finished:
            self.finished = True
            self.budget.finish(self.operation_id, success)

    async def __aiter__(self):
        size = 0
        try:
            async for chunk in self.response.aiter_raw():
                size += len(chunk)
                if size > 2_000_000:
                    raise BudgetDenied('stream_response_limit')
                marker = self.tail + chunk
                self.done_marker |= b'data: [DONE]' in marker
                self.tail = marker[-32:]
                yield chunk
            self.settle(200 <= self.response.status_code < 300)
        finally:
            await self.aclose()

    async def aclose(self):
        try:
            await self.response.aclose()
        finally:
            self.settle(self.done_marker and 200 <= self.response.status_code < 300)


class BudgetedSyncTransport(httpx.BaseTransport):
    def __init__(self, budget, endpoint, purpose, upstream=None, operation_id=None):
        self.budget, self.endpoint, self.purpose = budget, endpoint, purpose
        if upstream is not None and type(upstream) is not httpx.MockTransport:
            raise BudgetDenied("unapproved_custom_transport")
        if upstream is None and (not isinstance(operation_id, str) or not 8 <= len(operation_id) <= 200 or not operation_id.strip()):
            raise BudgetDenied("stable_operation_id_required")
        self.upstream = upstream or httpx.HTTPTransport(retries=0)
        self.operation_id = operation_id or uuid4().hex

    def handle_request(self, request):
        outgoing, request_digest = _prepare(request, self.budget, self.endpoint, self.purpose)
        self.budget.reserve(self.operation_id, request_digest, self.purpose)
        try:
            response = self.upstream.handle_request(outgoing)
            body = response.read()
        except BaseException:
            try:
                self.budget.finish(self.operation_id, False)
            except BudgetDenied:
                pass
            raise
        self.budget.finish(self.operation_id, 200 <= response.status_code < 300)
        return httpx.Response(response.status_code, headers=response.headers, content=body, request=request)

    def close(self):
        self.upstream.close()
