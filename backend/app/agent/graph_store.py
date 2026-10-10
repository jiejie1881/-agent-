"""Local persistent checkpoints for the single-instance Demo deployment."""
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from app.core.config import get_settings


class AgentGraphStore:
    def __init__(self, path=None):
        self.path = Path(path or get_settings().agent_checkpoint_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS agent_graph_actions (action_id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, conversation_id INTEGER NOT NULL, thread_id TEXT NOT NULL)')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(str(self.path), timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def register(self, action_id, user_id, conversation_id, thread_id):
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO agent_graph_actions VALUES (?, ?, ?, ?)', (action_id, user_id, conversation_id, thread_id))

    def find(self, action_id, user_id, conversation_id):
        with self.connection() as db:
            row = db.execute('SELECT thread_id FROM agent_graph_actions WHERE action_id=? AND user_id=? AND conversation_id=?', (action_id, user_id, conversation_id)).fetchone()
        return row[0] if row else None
