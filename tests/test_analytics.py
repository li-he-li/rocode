"""Analytics tests — MetricsCollector, ContextMemory round-trip, AuditDB aggregation, ResourceTracker."""

import json
import os
import tempfile
import time

import pytest


# ── MetricsCollector ──────────────────────────────────────────────────


class TestMetricsCollector:
    @pytest.fixture
    def metrics(self):
        from robocode.services.analytics.metrics import MetricsCollector

        return MetricsCollector()

    def test_record_counter(self, metrics):
        metrics.record("test_event")
        metrics.record("test_event", 3)
        assert metrics.get_counter("test_event") == 4

    def test_record_latency(self, metrics):
        metrics.record_latency("tool_execution", 150.0)
        metrics.record_latency("tool_execution", 250.0)
        lats = metrics.get_latencies("tool_execution")
        assert len(lats) == 2
        assert 150.0 in lats
        assert 250.0 in lats

    def test_timer_context_manager(self, metrics):
        with metrics.timer("tool_execution", tool_name="test"):
            pass
        assert metrics.get_counter("tool_execution_total") == 1
        lats = metrics.get_latencies("tool_execution")
        assert len(lats) == 1
        assert lats[0] >= 0

    def test_session_summary_empty(self, metrics):
        s = metrics.session_summary()
        assert s["tool_executions"]["total"] == 0
        assert s["safety_rejections"] == 0
        assert s["voice_operations"]["total"] == 0

    def test_session_summary_with_data(self, metrics):
        metrics.record_latency("tool_execution", 100.0)
        metrics.record_latency("tool_execution", 200.0)
        metrics.record("tool_execution_total", 2)
        metrics.record("safety_rejection", 3)
        s = metrics.session_summary()
        assert s["tool_executions"]["total"] == 2
        assert s["safety_rejections"] == 3
        assert s["tool_executions"]["p50_ms"] > 0

    def test_stt_metrics(self, metrics):
        metrics.record_stt_result(1000.0, 0.92, True)
        metrics.record_stt_result(2000.0, 0.85, True)
        metrics.record_stt_result(0, 0, False)
        vo = metrics.session_summary()["voice_operations"]
        assert vo["total"] == 3
        assert vo["success"] == 2
        assert vo["failure"] == 1
        assert vo["avg_latency_ms"] == 1500.0
        assert vo["avg_confidence"] == 0.885


# ── ContextMemory serialization ──────────────────────────────────────


class TestContextMemorySerialization:
    def test_round_trip_empty(self):
        from robocode.agent.context import ContextMemory

        ctx = ContextMemory()
        data = ctx.to_json()
        restored = ContextMemory.from_json(data)
        assert restored.messages == []
        assert restored.max_tokens == 15000

    def test_round_trip_with_messages(self):
        from robocode.agent.context import ContextMemory

        ctx = ContextMemory(max_tokens=9000)
        ctx.add_user_message("移动机械臂")
        ctx.add_assistant_message("好的，正在移动")
        ctx.add_tool_result("call_1", "move_xyz", '{"success":true}')
        ctx.safety_state = {"joint_ok": True}

        data = ctx.to_json()
        restored = ContextMemory.from_json(data)

        assert len(restored.messages) == 3
        assert restored.messages[0]["role"] == "user"
        assert restored.messages[0]["content"] == "移动机械臂"
        assert restored.messages[1]["role"] == "assistant"
        assert restored.messages[2]["role"] == "tool"
        assert restored.messages[2]["tool_call_id"] == "call_1"
        assert restored.max_tokens == 9000
        assert restored.safety_state == {"joint_ok": True}

    def test_round_trip_with_tool_calls(self):
        from robocode.agent.context import ContextMemory

        ctx = ContextMemory()
        ctx.add_user_message("执行操作")
        ctx.add_assistant_message(
            tool_calls=[
                {
                    "id": "t1",
                    "type": "function",
                    "function": {"name": "move_xyz", "arguments": '{"x":100}'},
                }
            ]
        )
        ctx.add_tool_result("t1", "move_xyz", '{"success":true}')

        data = ctx.to_json()
        restored = ContextMemory.from_json(data)

        assert len(restored.messages) == 3
        assert restored.messages[1].get("tool_calls") is not None
        assert restored.messages[1]["tool_calls"][0]["id"] == "t1"

    def test_from_json_defaults(self):
        from robocode.agent.context import ContextMemory

        ctx = ContextMemory.from_json("{}")
        assert ctx.messages == []
        assert ctx.max_tokens == 15000
        assert ctx.safety_state == {}


# ── AuditDB ───────────────────────────────────────────────────────────


class TestAuditDB:
    @pytest.fixture
    def db(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        from robocode.services.analytics.db import AuditDB

        db = AuditDB(path)
        db.initialize()
        yield db
        db.close()
        os.unlink(path)

    def test_init_creates_tables(self, db):
        tables = db.list_tables()
        assert "sessions" in tables
        assert "tool_calls" in tables
        assert "approvals" in tables
        assert "checkpoints" in tables

    def test_auto_migration_adds_columns(self, db):
        cols = {r["name"] for r in db.conn.execute("PRAGMA table_info(tool_calls)").fetchall()}
        assert "duration_ms" in cols
        session_cols = {
            r["name"] for r in db.conn.execute("PRAGMA table_info(sessions)").fetchall()
        }
        assert "ended_at" in session_cols

    def test_create_and_close_session(self, db):
        sid = db.create_session()
        s = db.get_session(sid)
        assert s["status"] == "active"

        db.close_session(sid)
        s = db.get_session(sid)
        assert s["status"] == "closed"
        assert s["ended_at"] is not None

    def test_record_tool_call_with_duration(self, db):
        sid = db.create_session()
        db.record_tool_call(sid, "test_tool", "L0", {}, {"success": True}, duration_ms=123.4)
        calls = db.list_tool_calls(sid)
        assert len(calls) == 1
        assert calls[0]["duration_ms"] == 123.4

    def test_tool_latency_stats(self, db):
        sid = db.create_session()
        db.record_tool_call(sid, "move_xyz", "L2", {}, {"success": True}, duration_ms=100)
        db.record_tool_call(sid, "move_xyz", "L2", {}, {"success": True}, duration_ms=200)
        db.record_tool_call(sid, "get_status", "L0", {}, {"success": True}, duration_ms=5)

        stats = db.tool_latency_stats(sid)
        move = next(s for s in stats if s["tool_name"] == "move_xyz")
        assert move["call_count"] == 2
        assert move["avg_ms"] == 150.0
        assert move["min_ms"] == 100.0
        assert move["max_ms"] == 200.0

    def test_session_summary(self, db):
        sid = db.create_session()
        db.record_tool_call(sid, "t1", "L0", {}, {"success": True}, duration_ms=10)
        db.record_tool_call(sid, "t2", "L1", {}, {"success": False}, duration_ms=20)
        ss = db.session_summary(sid)
        assert ss["total_calls"] == 2
        assert ss["total_duration_ms"] == 30

    def test_recent_sessions_with_stats(self, db):
        for _ in range(3):
            sid = db.create_session()
            db.record_tool_call(sid, "t", "L0", {}, {"success": True}, duration_ms=10)
        recent = db.recent_sessions_with_stats(limit=2)
        assert len(recent) == 2
        assert recent[0]["total_calls"] == 1

    def test_checkpoint_save_and_restore_context(self, db):
        from robocode.agent.context import ContextMemory

        sid = db.create_session()
        ctx = ContextMemory()
        ctx.add_user_message("hello")

        db.save_checkpoint(sid, "success", {"context_json": ctx.to_json()}, step_index=1)
        ck = db.get_latest_checkpoint(sid)
        assert ck is not None
        task_plan = json.loads(ck["task_plan"])
        restored = ContextMemory.from_json(task_plan["context_json"])
        assert len(restored.messages) == 1
        assert restored.messages[0]["content"] == "hello"

    def test_double_init_idempotent(self, db):
        db.initialize()
        tables = db.list_tables()
        assert "sessions" in tables


# ── ResourceTracker ───────────────────────────────────────────────────

# ── Display rendering ─────────────────────────────────────────────────


class TestDisplayRendering:
    @pytest.fixture
    def db_with_data(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        from robocode.services.analytics.db import AuditDB

        db = AuditDB(path)
        db.initialize()
        sid = db.create_session()
        db.record_tool_call(sid, "move_xyz", "L2", {}, {"success": True}, duration_ms=100)
        db.record_tool_call(sid, "move_xyz", "L2", {}, {"success": True}, duration_ms=300)
        db.record_tool_call(sid, "get_status", "L0", {}, {"success": True}, duration_ms=10)
        db.record_approval(sid, "move_xyz", "L2", False, rejected_by="operator")
        yield db
        db.close()
        os.unlink(path)

    @staticmethod
    def _render(panel) -> str:
        from rich.console import Console

        console = Console(width=120, force_terminal=False)
        with console.capture() as capture:
            console.print(panel)
        return capture.get()

    def test_render_session_list(self, db_with_data):
        from robocode.services.analytics.display import render_session_list

        panel = render_session_list(db_with_data)
        rendered = self._render(panel)
        assert "最近会话" in rendered

    def test_render_tool_stats_p50(self, db_with_data):
        from robocode.services.analytics.display import render_tool_stats

        panel = render_tool_stats(db_with_data)
        rendered = self._render(panel)
        assert "move_xyz" in rendered
        # P50 of [100, 300] with median at index len//2=1 → 300ms
        assert "100ms" in rendered or "300ms" in rendered

    def test_render_safety_stats(self, db_with_data):
        from robocode.services.analytics.display import render_safety_stats

        panel = render_safety_stats(db_with_data)
        rendered = self._render(panel)
        assert "operator" in rendered


class TestResourceTracker:
    @pytest.fixture
    def tracker(self):
        from robocode.services.analytics.resource_tracker import ResourceTracker

        return ResourceTracker()

    def test_track_and_cleanup_file(self, tracker, tmp_path):
        f = tmp_path / "test_temp.txt"
        f.write_text("data")
        tracker.track_file(f)
        assert tracker.pending()["files"] == 1

        tracker.cleanup()
        assert not f.exists()
        assert tracker.pending()["files"] == 0

    def test_pending_initial_zero(self, tracker):
        p = tracker.pending()
        assert p["files"] == 0
        assert p["processes"] == 0

    def test_detect_dirty_state_stale_files(self, tracker, tmp_path, monkeypatch):
        monkeypatch.setattr(tracker, "_temp_dir", tmp_path)
        old_file = tmp_path / "gen_old.py"
        old_file.write_text("old")
        # Set mtime to 48 hours ago
        old_time = time.time() - 48 * 3600
        os.utime(old_file, (old_time, old_time))

        msgs = tracker.detect_dirty_state()
        assert not old_file.exists()  # Should be auto-deleted
        assert any("已清理" in m for m in msgs)

    def test_detect_dirty_state_recent_files_kept(self, tracker, tmp_path, monkeypatch):
        monkeypatch.setattr(tracker, "_temp_dir", tmp_path)
        recent = tmp_path / "gen_recent.py"
        recent.write_text("recent")
        # File just created, < 24h

        tracker.detect_dirty_state()
        assert recent.exists()
