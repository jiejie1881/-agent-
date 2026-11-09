"""Local public-event journal; private plans never enter this store."""
import json
import sqlite3
from pathlib import Path


class StreamStore:
    def __init__(self, checkpoint_path):
        self.path = Path(checkpoint_path).parent / 'stream_events.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS events(user_id INTEGER, conversation_id INTEGER, message_id TEXT, sequence INTEGER, body TEXT NOT NULL, PRIMARY KEY(user_id,conversation_id,message_id,sequence))')
            db.execute('CREATE TABLE IF NOT EXISTS operations(user_id INTEGER, conversation_id INTEGER, operation_id TEXT, digest TEXT NOT NULL, message_id TEXT NOT NULL, PRIMARY KEY(user_id,conversation_id,operation_id))')

    def claim(self, user_id, conversation_id, operation_id, digest, message_id):
        with sqlite3.connect(self.path) as db:
            try:
                db.execute('INSERT INTO operations VALUES(?,?,?,?,?)',
                    (user_id, conversation_id, operation_id, digest, message_id))
                return None
            except sqlite3.IntegrityError:
                return db.execute('SELECT digest,message_id FROM operations WHERE user_id=? AND conversation_id=? AND operation_id=?',
                    (user_id, conversation_id, operation_id)).fetchone()

    def append(self, user_id, event):
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO events VALUES(?,?,?,?,?)', (user_id,
                event['conversation_id'], event['message_id'], event['sequence'], json.dumps(event, ensure_ascii=False)))

    def read(self, user_id, conversation_id, message_id, after=0):
        with sqlite3.connect(self.path) as db:
            return [json.loads(row[0]) for row in db.execute(
                'SELECT body FROM events WHERE user_id=? AND conversation_id=? AND message_id=? AND sequence>? ORDER BY sequence LIMIT 1000',
                (user_id, conversation_id, message_id, after))]

    def statistics(self, user_id, conversation_id):
        with sqlite3.connect(self.path) as db:
            events = [json.loads(row[0]) for row in db.execute(
                'SELECT body FROM events WHERE user_id=? AND conversation_id=?', (user_id, conversation_id))]
        runs = {e['message_id'] for e in events if e['event_type'] == 'message_start'}
        completed = [e for e in events if e['event_type'] == 'message_complete']
        successful = [e for e in completed if (e['payload'].get('execution') or {}).get('status') == 'COMPLETED']
        tools = [e for e in events if e['event_type'] == 'tool_call_result'
                 and e['payload'].get('status') in {'SUCCEEDED', 'CACHED', 'FAILED', 'TIMED_OUT'}]
        good_tools = [e for e in tools if e['payload']['status'] in {'SUCCEEDED', 'CACHED'}]
        metrics = [e['payload'] for e in events if e['event_type'] == 'model_metrics']
        return {'run_count': len(runs), 'agent_success_count': len(successful),
            'agent_success_denominator': len(runs),
            'agent_success_rate': len(successful)/len(runs) if runs else None,
            'tool_result_count': len(tools), 'tool_success_count': len(good_tools),
            'tool_success_rate': len(good_tools)/len(tools) if tools else None,
            'model_metrics_scope': 'streamed_final_model_calls_only',
            'measured_model_calls': metrics, 'quality_evaluation': 'NOT_RUN',
            'environments': sorted({e.get('environment', 'UNKNOWN') for e in events})}
