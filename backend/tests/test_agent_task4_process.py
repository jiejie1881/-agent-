"""Real owned processes, no database, network or model access."""
import asyncio
import json
import os
from pathlib import Path

import pytest

from app.agent import process_supervisor as supervisor
from app.agent.execution_control import ExecutionDeadlineError


WORKER = r'''
import json,os,signal,subprocess,sys,time
r=json.loads(sys.stdin.buffer.readline())
mode=r.get('mode','normal')
if mode=='parent_owner':
 sys.path[:0]=[r['backend'],*r['package_paths']]
 import asyncio
 # This is an OS supervisor lifecycle probe, not an AgentService startup
 # benchmark. Load the real module without unrelated eager package exports.
 import types
 package=types.ModuleType('app.agent');package.__path__=[r['backend']+'/app/agent']
 sys.modules['app.agent']=package
 from app.agent import process_supervisor as m
 m.__file__=r['supervisor_file']
 record={}
 async def own():
  task=asyncio.create_task(m.run_worker({'mode':'tree','pid_file':r['pid_file']},timeout_seconds=60,record=record))
  while not record.get('pid'):
   if task.done():await task
   await asyncio.sleep(.01)
  open(r['owner_record'],'w').write(json.dumps(record))
  await task
 asyncio.run(own());sys.exit(0)
if mode=='ignore':
 if os.name=='nt':signal.signal(signal.SIGBREAK,signal.SIG_IGN)
 else:signal.signal(signal.SIGTERM,signal.SIG_IGN)
if mode=='crash':os._exit(23)
if mode=='bad':print('not json',flush=True);sys.exit(0)
if mode=='oversize':print('x'*1100000,flush=True);sys.exit(0)
if mode in {'tree','sleep','ignore'}:
 if mode=='tree':
  child=subprocess.Popen([sys.executable,'-I','-S','-B','-c',
   "import subprocess,sys,time,json,os; p=subprocess.Popen([sys.executable,'-I','-S','-B','-c','import time;time.sleep(60)']);open(sys.argv[1],'w').write(json.dumps([os.getpid(),p.pid]));time.sleep(60)",r['pid_file']])
 time.sleep(60)
if mode=='late':time.sleep(.15)
print(json.dumps(dict(version=1,request_id=r['request_id'] if mode!='wrong' else 'other',ok=True,result={'pid':os.getpid()})),flush=True)
'''


def alive(pid):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes as w
        k=ctypes.WinDLL('kernel32',use_last_error=True)
        k.OpenProcess.restype=w.HANDLE;k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD]
        k.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD];k.CloseHandle.argtypes=[w.HANDLE]
        h=k.OpenProcess(0x100000,False,pid)
        if not h:return False
        try:return k.WaitForSingleObject(h,0)==258
        finally:k.CloseHandle(h)
    try:
        state=Path(f'/proc/{pid}/stat').read_text().split(')')[1].split()[0]
        return state!='Z'
    except FileNotFoundError:return False


@pytest.fixture
def worker(tmp_path,monkeypatch):
    path=tmp_path/'process_worker.py';path.write_text(WORKER,encoding='utf8')
    monkeypatch.setattr(supervisor,'__file__',str(tmp_path/'supervisor.py'))
    return path


def test_actual_normal_worker_is_reaped(worker):
    record={}
    result=asyncio.run(supervisor.run_worker({},timeout_seconds=5,record=record))
    assert result['pid']==record['pid']
    assert record['cleanup_confirmed'] and not alive(record['pid'])


@pytest.mark.parametrize('mode',['sleep','ignore','tree'])
def test_actual_timeout_reaps_tree(worker,tmp_path,mode):
    record={};pid_file=tmp_path/'pids.json'
    with pytest.raises(ExecutionDeadlineError):
        asyncio.run(supervisor.run_worker({'mode':mode,'pid_file':str(pid_file)},timeout_seconds=1,record=record))
    assert record['cleanup_confirmed'] and not alive(record['pid'])
    if mode=='tree':
        assert pid_file.exists()
        assert all(not alive(pid) for pid in json.loads(pid_file.read_text()))


@pytest.mark.parametrize('mode',['sleep','ignore','tree'])
def test_actual_cancel_reaps_tree_and_repeated_cancel(worker,tmp_path,mode):
    record={};pid_file=tmp_path/'pids.json'
    async def run():
        task=asyncio.create_task(supervisor.run_worker({'mode':mode,'pid_file':str(pid_file)},timeout_seconds=10,record=record))
        for _ in range(200):
            if record.get('pid') and (mode!='tree' or pid_file.exists()):break
            await asyncio.sleep(.01)
        task.cancel();await asyncio.sleep(.01);task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
    asyncio.run(run())
    assert record['cleanup_confirmed'] and not alive(record['pid'])
    if mode=='tree':assert all(not alive(pid) for pid in json.loads(pid_file.read_text()))


@pytest.mark.parametrize('mode',['crash','bad','wrong','oversize'])
def test_worker_protocol_fail_closed(worker,mode):
    record={}
    with pytest.raises(supervisor.WorkerFailure):
        asyncio.run(supervisor.run_worker({'mode':mode},timeout_seconds=5,record=record))
    assert record['cleanup_confirmed'] and not alive(record['pid'])


def test_start_failure_never_falls_back_to_shared_thread(worker,monkeypatch):
    def fail(*a,**kw):raise OSError('synthetic start failure')
    monkeypatch.setattr(supervisor.subprocess,'Popen',fail)
    with pytest.raises(OSError):asyncio.run(supervisor.run_worker({},timeout_seconds=1))


def test_concurrent_cancellation_does_not_affect_sibling(worker):
    records=[{},{}]
    async def run():
        first=asyncio.create_task(supervisor.run_worker({'mode':'sleep'},timeout_seconds=10,record=records[0]))
        second=asyncio.create_task(supervisor.run_worker({'mode':'late'},timeout_seconds=10,record=records[1]))
        for _ in range(300):
            if records[0].get('pid'):break
            if first.done():await first
            await asyncio.sleep(.01)
        assert records[0].get('pid'), 'Worker startup exceeded bounded wait'
        first.cancel()
        with pytest.raises(asyncio.CancelledError):await first
        assert (await second)['pid']==records[1]['pid']
    asyncio.run(run())
    assert all(r['cleanup_confirmed'] and not alive(r['pid']) for r in records)


@pytest.mark.parametrize('deadline',[0,-1,float('nan'),float('inf')])
def test_invalid_process_deadline_does_not_spawn(worker,deadline):
    record={}
    with pytest.raises(ValueError):asyncio.run(supervisor.run_worker({},timeout_seconds=deadline,record=record))
    assert not record


def test_non_serializable_request_never_spawns(worker):
    with pytest.raises(TypeError):asyncio.run(supervisor.run_worker({'bad':object()},timeout_seconds=1))


def test_capabilities_do_not_claim_rag_hard_cancel():
    from app.agent.tool_capabilities import capability
    from app.agent.tool_registry import DEFAULT_TOOL_DEFINITIONS,WRITE_TOOL_DEFINITIONS
    for definition in (*DEFAULT_TOOL_DEFINITIONS,*WRITE_TOOL_DEFINITIONS):
        result=capability(definition,process_enabled=True)
        if definition.name=='search_knowledge_base':
            assert result['capability']=='NON_CANCELLABLE' and not result['hard_termination']
        if not definition.read_only:
            assert result['capability']=='TRANSACTION_BOUNDED' and not result['automatic_write_retry']


def test_kill_failure_is_not_reported_as_cancel_success(worker,monkeypatch):
    if os.name!='nt':
        pytest.skip('Windows Job Object fault injection; POSIX coverage separate')
    def fail(self):raise supervisor.CleanupUnverified('synthetic kill failure')
    monkeypatch.setattr(supervisor._WindowsJob,'kill',fail)
    record={}
    with pytest.raises(supervisor.CleanupUnverified):
        asyncio.run(supervisor.run_worker({'mode':'sleep'},timeout_seconds=.2,record=record))
    assert not record['cleanup_confirmed']
    # Closing the containment handle is the independent safety fallback.
    import time
    until=time.monotonic()+3
    while alive(record['pid']) and time.monotonic()<until:time.sleep(.01)
    assert not alive(record['pid'])


def test_parent_death_closes_job_and_reaps_grandchildren(worker,tmp_path):
    if os.name!='nt':
        pytest.skip('Windows parent death contract; Linux pdeath signal separately reviewed')
    import subprocess
    import sys
    import time
    pid_file=tmp_path/'tree.json';owner_record=tmp_path/'owner.json'
    request=dict(mode='parent_owner',backend=str(Path(__file__).resolve().parents[1]),
        package_paths=[p for p in sys.path if Path(p).name=='site-packages'],
        supervisor_file=str(worker.with_name('supervisor.py')),pid_file=str(pid_file),owner_record=str(owner_record))
    parent=subprocess.Popen([sys._base_executable,'-I','-S','-B',str(worker)],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        parent.stdin.write(json.dumps(request).encode()+b'\n');parent.stdin.close()
        until=time.monotonic()+10
        while not (pid_file.exists() and owner_record.exists()) and time.monotonic()<until:
            assert parent.poll() is None, 'Probe owner failed before creating owned descendants'
            time.sleep(.02)
        assert pid_file.exists() and owner_record.exists()
        descendants=[json.loads(owner_record.read_text())['pid'],*json.loads(pid_file.read_text())]
        assert all(alive(pid) for pid in descendants)
        parent.kill();parent.wait(timeout=3)
        until=time.monotonic()+5
        while any(alive(pid) for pid in descendants) and time.monotonic()<until:time.sleep(.02)
        assert all(not alive(pid) for pid in descendants)
    finally:
        if parent.poll() is None:parent.kill();parent.wait(timeout=3)
        parent.stdout.close();parent.stderr.close()


def test_containment_failure_aborts_before_request(worker,monkeypatch):
    if os.name!='nt':pytest.skip('Windows containment setup failure')
    def fail(*a):raise supervisor.CleanupUnverified('synthetic containment failure')
    monkeypatch.setattr(supervisor,'_WindowsJob',fail)
    record={}
    with pytest.raises(supervisor.CleanupUnverified):
        asyncio.run(supervisor.run_worker({'mode':'sleep'},timeout_seconds=5,record=record))
    assert not alive(record['pid']) and not record['cleanup_confirmed']
