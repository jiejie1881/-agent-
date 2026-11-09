"""Local persistent checkpoints for the single-instance deployment."""
import sqlite3
import hashlib
import os
import json
from pathlib import Path
from contextlib import contextmanager
from app.core.config import get_settings
from app.domain.exceptions import AgentPendingActionError, NotFoundError


class AgentGraphStore:
    def __init__(self, path=None):
        self.path = Path(path or get_settings().agent_checkpoint_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS agent_graph_actions (action_id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, conversation_id INTEGER NOT NULL, thread_id TEXT NOT NULL)')
        # LangGraph's async saver may hold a checkpoint transaction while a node
        # is running. Telemetry must not synchronously lock that same database.
        self.execution_path=self.path.with_name(self.path.name+'.executions.sqlite3')
        with self.execution_connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS agent_execution_reports (execution_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, conversation_id INTEGER, report_json TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS agent_execution_threads (execution_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, conversation_id INTEGER, thread_id TEXT UNIQUE NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS agent_action_threads (action_id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, conversation_id INTEGER NOT NULL, thread_id TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS agent_execution_runtime (execution_id TEXT PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0, uncertain_write INTEGER NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS agent_step_receipts (execution_id TEXT NOT NULL, epoch INTEGER NOT NULL, step_id TEXT NOT NULL, argument_hash TEXT NOT NULL, result_json TEXT NOT NULL, PRIMARY KEY(execution_id,epoch,step_id))')
            db.execute('CREATE TABLE IF NOT EXISTS agent_execution_cancellations (execution_id TEXT PRIMARY KEY, requested INTEGER NOT NULL)')

    def request_cancellation(self,execution_id,user_id,conversation_id):
        self.thread(execution_id,user_id,conversation_id)
        with self.execution_connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT report_json FROM agent_execution_reports WHERE execution_id=? AND user_id=? AND conversation_id IS ?',
                (execution_id,user_id,conversation_id)).fetchone()
            if row is None:raise NotFoundError('Agent执行状态不存在')
            report=json.loads(row[0])
            if report['status'] not in {'RUNNING','RECOVERING','RETRYING'}:return False
            db.execute('INSERT INTO agent_execution_cancellations VALUES (?,1) ON CONFLICT(execution_id) DO NOTHING',(execution_id,))
        return True

    def cancellation_requested(self,execution_id):
        with self.execution_connection() as db:
            return db.execute('SELECT requested FROM agent_execution_cancellations WHERE execution_id=?',(execution_id,)).fetchone() is not None

    @contextmanager
    def connection(self):
        db = sqlite3.connect(str(self.path), timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def register(self, action_id, user_id, conversation_id, thread_id):
        with self.execution_connection() as db:
            db.execute('INSERT OR REPLACE INTO agent_action_threads VALUES (?, ?, ?, ?)', (action_id, user_id, conversation_id, thread_id))

    def find(self, action_id, user_id, conversation_id):
        with self.execution_connection() as db:
            row = db.execute('SELECT thread_id FROM agent_action_threads WHERE action_id=? AND user_id=? AND conversation_id=?', (action_id, user_id, conversation_id)).fetchone()
        if row is None:
            with self.connection() as db:
                row = db.execute('SELECT thread_id FROM agent_graph_actions WHERE action_id=? AND user_id=? AND conversation_id=?', (action_id, user_id, conversation_id)).fetchone()
        return row[0] if row else None

    def register_execution(self, execution_id, user_id, conversation_id, thread_id):
        with self.execution_connection() as db:
            db.execute('INSERT INTO agent_execution_threads VALUES (?,?,?,?)',
                       (execution_id, user_id, conversation_id, thread_id))
            db.execute('INSERT INTO agent_execution_runtime(execution_id) VALUES (?)',(execution_id,))

    def runtime(self,execution_id):
        with self.execution_connection() as db:
            row=db.execute('SELECT attempts,uncertain_write FROM agent_execution_runtime WHERE execution_id=?',(execution_id,)).fetchone()
        return (row[0],bool(row[1])) if row else (0,False)

    def reserve_attempt(self,execution_id,limit):
        with self.execution_connection() as db:
            changed=db.execute('UPDATE agent_execution_runtime SET attempts=attempts+1 WHERE execution_id=? AND attempts<?',(execution_id,limit)).rowcount
            if changed!=1:raise AgentPendingActionError('AGENT_TOOL_LIMIT','任务工具调用次数已达上限')
            return db.execute('SELECT attempts FROM agent_execution_runtime WHERE execution_id=?',(execution_id,)).fetchone()[0]

    def uncertain_write(self,execution_id,flag):
        with self.execution_connection() as db:
            db.execute('UPDATE agent_execution_runtime SET uncertain_write=? WHERE execution_id=?',(int(flag),execution_id))

    @staticmethod
    def argument_hash(tool,arguments):
        return hashlib.sha256(json.dumps([tool,arguments],sort_keys=True,ensure_ascii=False).encode()).hexdigest()

    def receipt(self,execution_id,epoch,step_id,tool,arguments):
        with self.execution_connection() as db:
            row=db.execute('SELECT argument_hash,result_json FROM agent_step_receipts WHERE execution_id=? AND epoch=? AND step_id=?',(execution_id,epoch,step_id)).fetchone()
        if row is None:return None
        if row[0]!=self.argument_hash(tool,arguments):raise AgentPendingActionError('AGENT_STATE_MISMATCH','恢复步骤参数与原执行不一致')
        return json.loads(row[1])

    def save_receipt(self,execution_id,epoch,step_id,tool,arguments,result):
        with self.execution_connection() as db:
            db.execute('INSERT INTO agent_step_receipts VALUES (?,?,?,?,?)',(execution_id,epoch,step_id,self.argument_hash(tool,arguments),json.dumps(result,ensure_ascii=False)))

    def available(self,user_id,conversation_id):
        try:
            with self.lease(user_id,conversation_id):return True
        except AgentPendingActionError:return False

    def thread(self, execution_id, user_id, conversation_id):
        with self.execution_connection() as db:
            row = db.execute('SELECT thread_id FROM agent_execution_threads WHERE execution_id=? AND user_id=? AND conversation_id IS ?',
                             (execution_id, user_id, conversation_id)).fetchone()
        if row is None:raise NotFoundError('Agent执行状态不存在')
        return row[0]

    def execution(self, execution_id, user_id, conversation_id):
        with self.execution_connection() as db:
            row = db.execute('SELECT report_json FROM agent_execution_reports WHERE execution_id=? AND user_id=? AND conversation_id IS ?',
                             (execution_id, user_id, conversation_id)).fetchone()
        if row is None:raise NotFoundError('Agent执行状态不存在')
        return json.loads(row[0])

    def save_execution(self,user_id,report):
        with self.execution_connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT user_id,conversation_id,report_json FROM agent_execution_reports WHERE execution_id=?',(report.execution_id,)).fetchone()
            if old and (old[0]!=user_id or old[1]!=report.conversation_id):raise NotFoundError('Agent执行状态不存在')
            if old:
                previous=json.loads(old[2])
                # Cancellation/timeout/uncertain commit are sticky. A fresh
                # execution ID is needed to retry; no delayed receipt can revive it.
                if previous['status'] in {'CANCELLED','TIMED_OUT','MANUAL_REVIEW','COMPLETION_UNKNOWN','COMPLETED','CLARIFICATION'}:
                    return previous.get('revision',0)
            revision=json.loads(old[2]).get('revision',0)+1 if old else 1
            payload=report.model_copy(update={'revision':revision}).model_dump_json()
            db.execute('INSERT INTO agent_execution_reports VALUES(?,?,?,?) ON CONFLICT(execution_id) DO UPDATE SET report_json=excluded.report_json',
                (report.execution_id,user_id,report.conversation_id,payload))
        return revision

    def executions(self,user_id,conversation_id):
        with self.execution_connection() as db:
            rows=db.execute('SELECT report_json FROM agent_execution_reports WHERE user_id=? AND conversation_id IS ? ORDER BY rowid DESC LIMIT 20',
                            (user_id,conversation_id)).fetchall()
        return [json.loads(row[0]) for row in rows]

    @contextmanager
    def lease(self,user_id,conversation_id):
        """Single-host OS lock; release on process death, never TTL-steal a live worker."""
        directory=self.execution_path.with_name(self.execution_path.name+'.locks')
        directory.mkdir(exist_ok=True)
        key=hashlib.sha256(f'{user_id}:{conversation_id}'.encode()).hexdigest()
        stream=(directory/(key+'.lock')).open('a+b');acquired=False
        try:
            stream.seek(0,os.SEEK_END)
            if stream.tell()==0:stream.write(b'0');stream.flush()
            stream.seek(0)
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                acquired=True
            except (OSError,BlockingIOError) as exc:
                raise AgentPendingActionError('AGENT_EXECUTION_BUSY','该会话已有任务执行中，请先刷新状态') from exc
            yield
        finally:
            if acquired:
                stream.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
            stream.close()

    @contextmanager
    def execution_connection(self):
        db=sqlite3.connect(str(self.execution_path),timeout=5)
        try:
            with db:yield db
        finally:db.close()
