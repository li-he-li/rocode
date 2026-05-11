"""SQLite audit and checkpoint database — analytics-enhanced.

Auto-migrates existing databases by adding missing columns.
Provides aggregation queries for /audit command.
"""

import sqlite3
import json
import time
import uuid
from pathlib import Path
from robocode.services.analytics.logger import get_logger

logger = get_logger("analytics.db")


class AuditDB:
    def __init__(self, path: str = "robocode_audit.db"):
        self.path = Path(path)
        self._conn: sqlite3.Connection | None = None
        self._initialized = False

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    # ── initialization + migration ──────────────────────────────────

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

            CREATE TABLE IF NOT EXISTS checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                timestamp REAL NOT NULL,
                state TEXT NOT NULL,
                task_plan TEXT DEFAULT '{}',
                step_index INTEGER DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE INDEX IF NOT EXISTS idx_tool_calls_sid ON tool_calls(session_id);
            CREATE INDEX IF NOT EXISTS idx_approvals_sid ON approvals(session_id);
            CREATE INDEX IF NOT EXISTS idx_checkpoints_sid ON checkpoints(session_id);
        """)
        self.conn.commit()
        self._auto_migrate()
        self._initialized = True

    def _auto_migrate(self):
        """Add missing columns to existing tables without breaking existing data."""
        existing_cols = {
            row["name"] for row in self.conn.execute("PRAGMA table_info(tool_calls)").fetchall()
        }
        if "duration_ms" not in existing_cols:
            self.conn.execute("ALTER TABLE tool_calls ADD COLUMN duration_ms REAL DEFAULT 0")
            self.conn.commit()

        session_cols = {
            row["name"] for row in self.conn.execute("PRAGMA table_info(sessions)").fetchall()
        }
        if "ended_at" not in session_cols:
            self.conn.execute("ALTER TABLE sessions ADD COLUMN ended_at REAL")
            self.conn.commit()

    def list_tables(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return [r["name"] for r in rows]

    # ── sessions ────────────────────────────────────────────────────

    def create_session(self, backend="sdk", provider="deepseek-v4") -> str:
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

    def close_session(self, session_id: str):
        """Mark session as closed with ended_at timestamp."""
        now = time.time()
        self.conn.execute(
            "UPDATE sessions SET status='closed', ended_at=? WHERE id=?",
            (now, session_id),
        )
        self.conn.commit()

    # ── tool calls ──────────────────────────────────────────────────

    def record_tool_call(
        self,
        session_id,
        tool_name,
        risk_level,
        params,
        result,
        backend="sdk",
        duration_ms: float = 0,
    ):
        self.conn.execute(
            "INSERT INTO tool_calls (session_id, timestamp, tool_name, risk_level, params, result, backend, duration_ms) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                session_id,
                time.time(),
                tool_name,
                risk_level,
                json.dumps(params, ensure_ascii=False),
                json.dumps(result, ensure_ascii=False),
                backend,
                duration_ms,
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

    # ── approvals ───────────────────────────────────────────────────

    def record_approval(self, session_id, tool_name, risk_level, approved, rejected_by=None):
        self.conn.execute(
            "INSERT INTO approvals (session_id, timestamp, tool_name, risk_level, approved, rejected_by) "
            "VALUES (?,?,?,?,?,?)",
            (
                session_id,
                time.time(),
                tool_name,
                risk_level,
                1 if approved else 0,
                rejected_by,
            ),
        )
        self._touch_session(session_id)
        self.conn.commit()

    def list_approvals(self, session_id) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM approvals WHERE session_id=? ORDER BY timestamp ASC",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── checkpoints ─────────────────────────────────────────────────

    def save_checkpoint(self, session_id, state, task_plan, step_index=0):
        self.conn.execute(
            "INSERT OR REPLACE INTO checkpoints (session_id, timestamp, state, task_plan, step_index) "
            "VALUES (?,?,?,?,?)",
            (
                session_id,
                time.time(),
                state,
                json.dumps(task_plan, ensure_ascii=False),
                step_index,
            ),
        )
        self._touch_session(session_id)
        self.conn.commit()

    def get_latest_checkpoint(self, session_id) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM checkpoints WHERE session_id=? ORDER BY timestamp DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None

    # ── aggregation queries ─────────────────────────────────────────

    def tool_latency_stats(self, session_id: str) -> list[dict]:
        """Per-tool latency: avg/min/max/p50/p95 by tool_name."""
        rows = self.conn.execute(
            """
            SELECT tool_name,
                   COUNT(*) as call_count,
                   AVG(duration_ms) as avg_ms,
                   MIN(duration_ms) as min_ms,
                   MAX(duration_ms) as max_ms
            FROM tool_calls
            WHERE session_id=? AND duration_ms > 0
            GROUP BY tool_name
            ORDER BY call_count DESC
            """,
            (session_id,),
        ).fetchall()
        results = []
        for r in rows:
            rd = dict(r)
            raw = self.conn.execute(
                "SELECT duration_ms FROM tool_calls WHERE session_id=? AND tool_name=? AND duration_ms > 0 ORDER BY duration_ms",
                (session_id, rd["tool_name"]),
            ).fetchall()
            if raw:
                vals = [row["duration_ms"] for row in raw]
                p50_idx = len(vals) // 2
                p95_idx = int(len(vals) * 0.95)
                rd["p50_ms"] = vals[min(p50_idx, len(vals) - 1)]
                rd["p95_ms"] = vals[min(p95_idx, len(vals) - 1)]
            else:
                rd["p50_ms"] = 0
                rd["p95_ms"] = 0
            results.append(rd)
        return results

    def tool_success_rate(self, session_id: str) -> list[dict]:
        """Per-tool success/failure counts."""
        rows = self.conn.execute(
            """
            SELECT tool_name,
                   COUNT(*) as total,
                   SUM(CASE WHEN json_extract(result, '$.success') = 'true' THEN 1 ELSE 0 END) as success,
                   SUM(CASE WHEN json_extract(result, '$.success') = 'false' THEN 1 ELSE 0 END) as failure
            FROM tool_calls
            WHERE session_id=?
            GROUP BY tool_name
            ORDER BY total DESC
            """,
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def session_summary(self, session_id: str) -> dict:
        """Aggregated session stats: total calls, success rate, duration."""
        row = self.conn.execute(
            """
            SELECT s.id, s.created_at, s.ended_at, s.backend, s.status,
                   COUNT(tc.id) as total_calls,
                   SUM(CASE WHEN json_extract(tc.result, '$.success') = 'true' THEN 1 ELSE 0 END) as success_calls,
                   SUM(tc.duration_ms) as total_duration_ms
            FROM sessions s
            LEFT JOIN tool_calls tc ON tc.session_id = s.id
            WHERE s.id = ?
            GROUP BY s.id
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            return {}
        return dict(row)

    def safety_rejection_stats(self, session_id: str) -> list[dict]:
        """Rejection count by reason."""
        rows = self.conn.execute(
            """
            SELECT COALESCE(rejected_by, 'unknown') as reason,
                   COUNT(*) as count
            FROM approvals
            WHERE session_id=? AND approved = 0
            GROUP BY rejected_by
            ORDER BY count DESC
            """,
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def recent_sessions_with_stats(self, limit=5) -> list[dict]:
        """Recent sessions with aggregated metrics."""
        rows = self.conn.execute(
            """
            SELECT s.id, s.created_at, s.ended_at, s.backend, s.status,
                   COUNT(tc.id) as total_calls,
                   SUM(CASE WHEN json_extract(tc.result, '$.success') = 'true' THEN 1 ELSE 0 END) as success_calls,
                   COALESCE(SUM(tc.duration_ms), 0) as total_duration_ms
            FROM sessions s
            LEFT JOIN tool_calls tc ON tc.session_id = s.id
            GROUP BY s.id
            ORDER BY s.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── internal ────────────────────────────────────────────────────

    def _touch_session(self, session_id):
        self.conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (time.time(), session_id))

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
