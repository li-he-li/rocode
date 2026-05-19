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
        """Add missing columns and tables without breaking existing data."""
        # ── tool_calls columns ──────────────────────────────────────
        existing_cols = {
            row["name"] for row in self.conn.execute("PRAGMA table_info(tool_calls)").fetchall()
        }
        _tool_calls_additions = [
            ("duration_ms", "REAL DEFAULT 0"),
            ("physics_captured", "INTEGER DEFAULT 0"),
            ("annotated", "INTEGER DEFAULT 0"),
            ("task_instruction", "TEXT"),
            ("turn_number", "INTEGER"),
            ("prev_call_id", "INTEGER"),
        ]
        for col_name, col_type in _tool_calls_additions:
            if col_name not in existing_cols:
                self.conn.execute(f"ALTER TABLE tool_calls ADD COLUMN {col_name} {col_type}")
                self.conn.commit()

        session_cols = {
            row["name"] for row in self.conn.execute("PRAGMA table_info(sessions)").fetchall()
        }
        if "ended_at" not in session_cols:
            self.conn.execute("ALTER TABLE sessions ADD COLUMN ended_at REAL")
            self.conn.commit()

        # ── new tables ──────────────────────────────────────────────
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS tool_physics_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_call_id INTEGER,
                session_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                joint_angles_before TEXT,
                joint_angles_after TEXT,
                duration_ms REAL,
                speed_ratio REAL,
                captured INTEGER DEFAULT 0,
                created_at REAL NOT NULL,
                FOREIGN KEY (tool_call_id) REFERENCES tool_calls(id),
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS tool_annotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_call_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                category TEXT NOT NULL,
                choices TEXT DEFAULT '{}',
                is_failure INTEGER DEFAULT 0,
                free_text TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY (tool_call_id) REFERENCES tool_calls(id),
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS experience_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                file_path TEXT,
                details TEXT DEFAULT '{}',
                created_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_physics_sid ON tool_physics_data(session_id);
            CREATE INDEX IF NOT EXISTS idx_physics_callid ON tool_physics_data(tool_call_id);
            CREATE INDEX IF NOT EXISTS idx_annotations_sid ON tool_annotations(session_id);
            CREATE INDEX IF NOT EXISTS idx_annotations_callid ON tool_annotations(tool_call_id);
        """)
        self.conn.commit()

        physics_cols = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(tool_physics_data)").fetchall()
        }
        if "processed" not in physics_cols:
            self.conn.execute(
                "ALTER TABLE tool_physics_data ADD COLUMN processed INTEGER DEFAULT 0"
            )
            self.conn.commit()

        annotation_cols = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(tool_annotations)").fetchall()
        }
        if "processed" not in annotation_cols:
            self.conn.execute("ALTER TABLE tool_annotations ADD COLUMN processed INTEGER DEFAULT 0")
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
        task_instruction: str | None = None,
        turn_number: int | None = None,
        prev_call_id: int | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO tool_calls "
            "(session_id, timestamp, tool_name, risk_level, params, result, backend, duration_ms, "
            " task_instruction, turn_number, prev_call_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                session_id,
                time.time(),
                tool_name,
                risk_level,
                json.dumps(params, ensure_ascii=False),
                json.dumps(result, ensure_ascii=False),
                backend,
                duration_ms,
                task_instruction,
                turn_number,
                prev_call_id,
            ),
        )
        self._touch_session(session_id)
        self.conn.commit()
        return cur.lastrowid

    def list_tool_calls(self, session_id, limit=100) -> list[dict]:
        if session_id:
            rows = self.conn.execute(
                "SELECT * FROM tool_calls WHERE session_id=? ORDER BY timestamp ASC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM tool_calls ORDER BY timestamp ASC LIMIT ?",
                (limit,),
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
                    SUM(CASE WHEN json_extract(result, '$.success') IN (1, 'true') THEN 1 ELSE 0 END) as success,
                    SUM(CASE WHEN json_extract(result, '$.success') IN (0, 'false') OR json_extract(result, '$.success') IS NULL THEN 1 ELSE 0 END) as failure
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
                   SUM(CASE WHEN json_extract(tc.result, '$.success') IN (1, 'true') THEN 1 ELSE 0 END) as success_calls,
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
        """Recent sessions with aggregated metrics including physics and annotation coverage."""
        rows = self.conn.execute(
            """
            SELECT s.id, s.created_at, s.ended_at, s.backend, s.status,
                   COUNT(tc.id) as total_calls,
                   SUM(CASE WHEN json_extract(tc.result, '$.success') = 1 THEN 1 ELSE 0 END) as success_calls,
                   COALESCE(SUM(tc.duration_ms), 0) as total_duration_ms,
                   COALESCE(SUM(CASE WHEN tc.physics_captured=1 THEN 1 ELSE 0 END), 0) as physics_captured,
                   COALESCE(SUM(CASE WHEN tc.annotated=1 THEN 1 ELSE 0 END), 0) as annotated
            FROM sessions s
            LEFT JOIN tool_calls tc ON tc.session_id = s.id
            GROUP BY s.id
            ORDER BY s.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── physics data ──────────────────────────────────────────────────

    def insert_physics_data(
        self,
        tool_call_id: int,
        session_id: str,
        tool_name: str,
        joint_angles_before: list | None = None,
        joint_angles_after: list | None = None,
        duration_ms: float = 0,
        speed_ratio: float = 1.0,
    ):
        self.conn.execute(
            "INSERT INTO tool_physics_data "
            "(tool_call_id, session_id, tool_name, joint_angles_before, joint_angles_after, "
            " duration_ms, speed_ratio, captured, created_at) "
            "VALUES (?,?,?,?,?,?,?,1,?)",
            (
                tool_call_id,
                session_id,
                tool_name,
                json.dumps(joint_angles_before) if joint_angles_before is not None else None,
                json.dumps(joint_angles_after) if joint_angles_after is not None else None,
                duration_ms,
                speed_ratio,
                time.time(),
            ),
        )
        self.conn.commit()

    def get_unprocessed_physics(self, session_id: str | None = None) -> list[dict]:
        if session_id:
            rows = self.conn.execute(
                "SELECT * FROM tool_physics_data WHERE session_id=? AND (processed IS NULL OR processed=0) ORDER BY id",
                (session_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM tool_physics_data WHERE (processed IS NULL OR processed=0) ORDER BY id"
            ).fetchall()
        return [dict(r) for r in rows]

    # ── annotations ───────────────────────────────────────────────────

    def insert_annotation(
        self,
        tool_call_id: int,
        session_id: str,
        category: str,
        choices: dict | None = None,
        is_failure: bool = False,
        free_text: str = "",
    ):
        self.conn.execute(
            "INSERT INTO tool_annotations "
            "(tool_call_id, session_id, category, choices, is_failure, free_text, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                tool_call_id,
                session_id,
                category,
                json.dumps(choices or {}, ensure_ascii=False),
                1 if is_failure else 0,
                free_text,
                time.time(),
            ),
        )
        self.conn.execute(
            "UPDATE tool_calls SET annotated=1 WHERE id=?",
            (tool_call_id,),
        )
        self.conn.commit()

    def get_unprocessed_annotations(self, session_id: str | None = None) -> list[dict]:
        if session_id:
            rows = self.conn.execute(
                "SELECT * FROM tool_annotations WHERE session_id=? AND (processed IS NULL OR processed=0) ORDER BY id",
                (session_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM tool_annotations WHERE (processed IS NULL OR processed=0) ORDER BY id"
            ).fetchall()
        return [dict(r) for r in rows]

    # ── experience log ─────────────────────────────────────────────────

    def insert_experience_log(
        self, event_type: str, file_path: str = "", details: dict | None = None
    ):
        self.conn.execute(
            "INSERT INTO experience_log (event_type, file_path, details, created_at) "
            "VALUES (?,?,?,?)",
            (event_type, file_path, json.dumps(details or {}, ensure_ascii=False), time.time()),
        )
        self.conn.commit()

    def mark_physics_processed(self, session_id: str = ""):
        if session_id:
            self.conn.execute(
                "UPDATE tool_physics_data SET processed=1 WHERE session_id=?", (session_id,)
            )
        else:
            self.conn.execute(
                "UPDATE tool_physics_data SET processed=1 WHERE processed=0 OR processed IS NULL"
            )
        self.conn.commit()

    def mark_annotations_processed(self, session_id: str = ""):
        if session_id:
            self.conn.execute(
                "UPDATE tool_annotations SET processed=1 WHERE session_id=?", (session_id,)
            )
        else:
            self.conn.execute(
                "UPDATE tool_annotations SET processed=1 WHERE processed=0 OR processed IS NULL"
            )
        self.conn.commit()

    # ── interrupt cleanup ──────────────────────────────────────────────

    def cleanup_interrupted_session(self, session_id: str):
        """Mark interrupted session as closed. Physics data preserved for experience generation."""
        self.conn.execute(
            "UPDATE sessions SET status='closed', ended_at=? WHERE id=?",
            (time.time(), session_id),
        )
        self.conn.commit()
        logger.info("interrupted_session_closed", session_id=session_id)

    # ── TTL cleanup ───────────────────────────────────────────────────

    def cleanup_old_sessions(self, ttl_days: int = 7) -> int:
        """Delete sessions older than ttl_days with all related records.

        Cascade order: child tables first, then sessions.
        Returns number of sessions deleted.
        """
        cutoff = time.time() - ttl_days * 86400
        rows = self.conn.execute(
            "SELECT id FROM sessions WHERE created_at < ?", (cutoff,)
        ).fetchall()
        if not rows:
            return 0

        session_ids = [r["id"] for r in rows]
        deleted = 0

        for sid in session_ids:
            self._delete_session_cascade(sid)
            deleted += 1

        self.conn.commit()
        logger.info("old_sessions_cleaned", count=deleted, ttl_days=ttl_days)
        return deleted

    def cleanup_empty_sessions(self, current_session_id: str = "") -> int:
        """Delete sessions with 0 tool calls, excluding current_session_id."""
        rows = self.conn.execute(
            "SELECT s.id FROM sessions s "
            "LEFT JOIN tool_calls tc ON tc.session_id = s.id "
            "WHERE tc.id IS NULL AND s.id != ?",
            (current_session_id,),
        ).fetchall()
        if not rows:
            return 0

        deleted = 0
        for r in rows:
            self._delete_session_cascade(r["id"])
            deleted += 1

        self.conn.commit()
        logger.info("empty_sessions_cleaned", count=deleted)
        return deleted

    def _delete_session_cascade(self, session_id: str):
        """Delete a session and all related records across all tables."""
        _all_tables = (
            "tool_physics_data",
            "tool_annotations",
            "tool_calls",
            "approvals",
            "checkpoints",
        )
        for table in _all_tables:
            try:
                self.conn.execute(f"DELETE FROM {table} WHERE session_id=?", (session_id,))
            except Exception:
                pass  # table doesn't exist yet
        self.conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))

    # ── stats queries ──────────────────────────────────────────────────

    def annotation_stats(self, session_id: str) -> dict:
        row = self.conn.execute(
            "SELECT COUNT(*) as total_calls, "
            "SUM(CASE WHEN annotated=1 THEN 1 ELSE 0 END) as annotated_count "
            "FROM tool_calls WHERE session_id=? AND risk_level IN ('L1','L2')",
            (session_id,),
        ).fetchone()
        if row is None:
            return {}
        return dict(row)

    def physics_stats(self, session_id: str) -> dict:
        row = self.conn.execute(
            "SELECT COUNT(*) as total_physics, "
            "AVG(duration_ms) as avg_duration_ms "
            "FROM tool_physics_data WHERE session_id=?",
            (session_id,),
        ).fetchone()
        return dict(row) if row else {}

    # ── internal ────────────────────────────────────────────────────

    def _touch_session(self, session_id):
        self.conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (time.time(), session_id))

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
