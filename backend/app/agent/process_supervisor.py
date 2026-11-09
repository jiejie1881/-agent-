"""Private JSON RPC worker, gated before imports; no shell, pickle or shared ORM.

Windows Job Objects kill descendants when the owning parent dies. On POSIX a
session isolates the process tree; the worker installs a parent-death handler.
Failure to attach containment aborts BEFORE sending any request or credentials.
"""
from __future__ import annotations

import asyncio
import ctypes
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
from time import monotonic
from uuid import uuid4

from app.agent.execution_control import ExecutionDeadlineError

MAX_FRAME = 1024 * 1024


class WorkerFailure(RuntimeError):
    pass


class CleanupUnverified(WorkerFailure):
    pass


class _WindowsJob:
    def __init__(self, process):
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_ = [('a', ctypes.c_int64), ('b', ctypes.c_int64), ('flags', w.DWORD),
                        ('min', ctypes.c_size_t), ('max', ctypes.c_size_t),
                        ('limit', w.DWORD), ('affinity', ctypes.c_size_t),
                        ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ('r', 'w', 'o', 'rb', 'wb', 'ob')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process', ctypes.c_size_t),
                        ('job', ctypes.c_size_t), ('peakp', ctypes.c_size_t), ('peakj', ctypes.c_size_t)]
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.k.CreateJobObjectW.restype = w.HANDLE
        self.k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.k.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        self.k.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.k.CreateJobObjectW(None, None)
        info = Extended(); info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.handle:
            raise CleanupUnverified('Cannot create containment job')
        if not (self.k.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info))
                and self.k.AssignProcessToJobObject(self.handle, int(process._handle))):
            self.close()
            raise CleanupUnverified('Cannot contain worker; request not sent')

    def kill(self):
        if not self.k.TerminateJobObject(self.handle, 137):
            raise CleanupUnverified('Cannot terminate worker job')
        # TerminateJobObject returns before every descendant necessarily exits.
        # Query the actual job membership, rather than inferring it from pipes.
        from ctypes import wintypes as w
        class Accounting(ctypes.Structure):
            _fields_ = [(n, ctypes.c_int64) for n in ('user','kernel','period_user','period_kernel')] + [
                (n,w.DWORD) for n in ('faults','total','active','terminated')]
        self.k.QueryInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.c_void_p]
        limit=monotonic()+3
        while True:
            info=Accounting()
            if not self.k.QueryInformationJobObject(self.handle,1,ctypes.byref(info),ctypes.sizeof(info),None):
                raise CleanupUnverified('Cannot verify worker job exit')
            if not info.active:return
            if monotonic()>=limit:raise CleanupUnverified('Worker descendants have not exited')
            threading.Event().wait(.01)

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle); self.handle = None


def _blocking_rpc(request, timeout_seconds, cancel, record):
    if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 3600:
        raise ValueError('Finite positive worker timeout required')
    frame = json.dumps(request, ensure_ascii=False, allow_nan=False).encode('utf8')
    if len(frame) > MAX_FRAME:
        raise ValueError('Worker request too large')
    script = Path(__file__).with_name('process_worker.py')
    # Base executable avoids the Windows venv launcher spawning an uncontained
    # child before job assignment. Trusted package locations go over stdin.
    argv = [sys._base_executable, '-I', '-S', '-B', str(script)]
    env = {k: os.environ[k] for k in ('SystemRoot', 'WINDIR', 'PATH', 'TEMP', 'TMP') if k in os.environ}
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=env, start_new_session=os.name != 'nt',
                               creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
    record.update(pid=process.pid, request_id=request['request_id'], cleanup_confirmed=False)
    job = None
    response = bytearray(); overflow = threading.Event()
    def read():
        while True:
            block = process.stdout.read(4096)
            if not block:
                return
            if len(response) + len(block) > MAX_FRAME:
                overflow.set(); return
            response.extend(block)
    reader = threading.Thread(target=read, daemon=True)
    def drain_errors():
        while process.stderr.read(4096):
            pass  # no unbounded storage or disclosure of SQL/credentials
    error_reader = threading.Thread(target=drain_errors, daemon=True)
    deadline = monotonic() + timeout_seconds
    stopped = False
    try:
        if os.name == 'nt':
            job = _WindowsJob(process)
        reader.start()
        error_reader.start()
        process.stdin.write(frame + b'\n'); process.stdin.close()
        while process.poll() is None:
            if cancel.is_set() or monotonic() >= deadline or overflow.is_set():
                stopped = True
                break
            cancel.wait(.02)
        if stopped:
            # CTRL_BREAK is advisory; the Job/process-group kill below is the
            # actual boundary. Never send a signal to a shared server process.
            try:
                if os.name == 'nt': process.send_signal(signal.CTRL_BREAK_EVENT)
                else: os.killpg(process.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
            try: process.wait(timeout=.5)
            except subprocess.TimeoutExpired: pass
        # Always close the entire containment, including descendants surviving
        # a normal root exit. Do not trust a successful root return code alone.
        if job:
            job.kill()
        else:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        process.wait(timeout=3)
        reader.join(timeout=3)
        error_reader.join(timeout=3)
        if reader.is_alive() or error_reader.is_alive():
            raise CleanupUnverified('Worker output channel did not close')
        record.update(exit_code=process.returncode, cleanup_confirmed=True)
        if overflow.is_set(): raise WorkerFailure('Worker frame exceeds protocol limit')
        if cancel.is_set(): raise asyncio.CancelledError()
        if stopped or monotonic() >= deadline: raise ExecutionDeadlineError()
        if process.returncode != 0: raise WorkerFailure('Worker exited without a valid result')
        try: result = json.loads(response)
        except (ValueError, UnicodeError) as exc: raise WorkerFailure('Invalid worker IPC') from exc
        if not isinstance(result, dict) or result.get('request_id') != request['request_id'] or result.get('version') != 1:
            raise WorkerFailure('Worker response identity mismatch')
        if not result.get('ok'): raise WorkerFailure('Worker rejected operation: ' + str(result.get('code', 'UNKNOWN')))
        return result['result']
    finally:
        if job:
            job.close()  # Parent death/exception also closes this non-inherited handle.
        elif process.poll() is None:
            try:
                if os.name == 'nt': process.kill()
                else: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        if process.poll() is None:
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired as exc: raise CleanupUnverified('Worker exit not confirmed') from exc
        if process.stdin and not process.stdin.closed: process.stdin.close()
        if process.stdout: process.stdout.close()
        if process.stderr: process.stderr.close()


async def run_worker(payload, *, timeout_seconds, record=None):
    request = {**payload, 'version': 1, 'request_id': uuid4().hex,
               'backend': str(Path(__file__).resolve().parents[2]),
               'package_paths': [p for p in sys.path if Path(p).name in {'site-packages', 'dist-packages'}]}
    cancel = threading.Event()
    result = asyncio.create_task(asyncio.to_thread(_blocking_rpc, request, timeout_seconds, cancel,
                                                 record if record is not None else {}))
    try:
        return await asyncio.shield(result)
    except asyncio.CancelledError:
        cancel.set()
        # Repeated cancellation must not orphan the supervising thread.
        while not result.done():
            try: await asyncio.shield(result)
            except asyncio.CancelledError: continue
        if not result.cancelled():
            error = result.exception()
            if error is not None and not isinstance(error, asyncio.CancelledError): raise error
        raise
