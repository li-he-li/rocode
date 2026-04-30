"""SQLite audit and checkpoint database."""

import sqlite3
import json
import time
from pathlib import Path


class AuditDB:
    def __init__(self, path: str = "robocode_audit.db"):
        self.path = Path(path)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def initialize(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                backend TEXT DEFAULT 'sdk',
                provider TEXT DEFAULT 'deepseek-v4',
                status TEXT DEFAULT 'active'
            );

            CREATE TABLE IF NOT EXISTS tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                tool_name TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                params TEXT DEFAULT '{}',
                result TEXT DEFAULT '{}',
                backend TEXT DEFAULT 'sdk',
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                tool_name TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                approved INTEGER NOT NULL,
                rejected_by TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS safety_rejections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                tool_name TEXT NOT NULL,
                reason TEXT NOT NULL,
                check_type TEXT DEFAULT '',
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                timestamp REAL NOT NULL,
                state TEXT NOT NULL,
                task_plan TEXT DEFAULT '{}',
                step_index INTEGER DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                name TEXT NOT NULL,
                path TEXT NOT NULL,
                kind TEXT DEFAULT '',
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE INDEX IF NOT EXISTS idx_tool_calls_sid ON tool_calls(session_id);
            CREATE INDEX IF NOT EXISTS idx_approvals_sid ON approvals(session_id);
            CREATE INDEX IF NOT EXISTS idx_checkpoints_sid ON checkpoints(session_id);
        """)
        self.conn.commit()

    def list_tables(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return [r["name"] for r in rows]

    # ── sessions ──

    def create_session(self, backend="sdk", provider="deepseek-v4") -> str:
        import uuid

        sid = uuid.uuid4().hex[:12]
        now = time.time()
        self.conn.execute(
            "INSERT INTO sessions (id, created_at, updated_at, backend, provider) VALUES (?,?,?,?,?)",
            (sid, now, now, backend, provider),
        )
        self.conn.commit()
        return sid

    def get_session(self, session_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        return dict(row) if row else None

    def list_sessions(self, limit=20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── tool calls ──

    def record_tool_call(self, session_id, tool_name, risk_level, params, result, backend="sdk"):
        self.conn.execute(
            "INSERT INTO tool_calls (session_id, timestamp, tool_name, risk_level, params, result, backend) VALUES (?,?,?,?,?,?,?)",
            (
                session_id,
                time.time(),
                tool_name,
                risk_level,
                json.dumps(params, ensure_ascii=False),
                json.dumps(result, ensure_ascii=False),
                backend,
            ),
        )
        self._touch_session(session_id)
        self.conn.commit()

    def list_tool_calls(self, session_id, limit=100) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM tool_calls WHERE session_id=? ORDER BY timestamp ASC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── approvals ──

    def record_approval(self, session_id, tool_name, risk_level, approved, rejected_by=None):
        self.conn.execute(
            "INSERT INTO approvals (session_id, timestamp, tool_name, risk_level, approved, rejected_by) VALUES (?,?,?,?,?,?)",
            (session_id, time.time(), tool_name, risk_level, 1 if approved else 0, rejected_by),
        )
        self._touch_session(session_id)
        self.conn.commit()

    def list_approvals(self, session_id) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM approvals WHERE session_id=? ORDER BY timestamp ASC", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── safety rejections ──

    def record_safety_rejection(self, session_id, tool_name, reason, check_type=""):
        self.conn.execute(
            "INSERT INTO safety_rejections (session_id, timestamp, tool_name, reason, check_type) VALUES (?,?,?,?,?)",
            (session_id, time.time(), tool_name, reason, check_type),
        )
        self._touch_session(session_id)
        self.conn.commit()

    def list_safety_rejections(self, session_id) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM safety_rejections WHERE session_id=? ORDER BY timestamp ASC",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── checkpoints ──

    def save_checkpoint(self, session_id, state, task_plan, step_index=0):
        self.conn.execute(
            "INSERT OR REPLACE INTO checkpoints (session_id, timestamp, state, task_plan, step_index) VALUES (?,?,?,?,?)",
            (session_id, time.time(), state, json.dumps(task_plan, ensure_ascii=False), step_index),
        )
        self._touch_session(session_id)
        self.conn.commit()

    def get_latest_checkpoint(self, session_id) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM checkpoints WHERE session_id=? ORDER BY timestamp DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if row:
            return dict(row)
        return None

    # ── artifacts ──

    def record_artifact(self, session_id, name, path, kind=""):
        self.conn.execute(
            "INSERT INTO artifacts (session_id, timestamp, name, path, kind) VALUES (?,?,?,?,?)",
            (session_id, time.time(), name, path, kind),
        )
        self.conn.commit()

    def list_artifacts(self, session_id) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM artifacts WHERE session_id=? ORDER BY timestamp ASC", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── internal ──

    def _touch_session(self, session_id):
        self.conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (time.time(), session_id))

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
