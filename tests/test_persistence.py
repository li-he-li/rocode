"""Persistence tests — SQLite schema, audit, checkpoint, resume."""

import pytest
import tempfile
import os


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


class TestDatabaseInit:
    def test_create_schema(self, db_path):
        from robocode.persistence.db import AuditDB

        db = AuditDB(db_path)
        db.initialize()
        tables = db.list_tables()
        assert "sessions" in tables
        assert "tool_calls" in tables
        assert "approvals" in tables
        assert "checkpoints" in tables
        db.close()

    def test_double_init_idempotent(self, db_path):
        from robocode.persistence.db import AuditDB

        db = AuditDB(db_path)
        db.initialize()
        db.initialize()  # no error
        db.close()


class TestSessions:
    def test_create_and_get_session(self, db_path):
        from robocode.persistence.db import AuditDB

        db = AuditDB(db_path)
        db.initialize()
        sid = db.create_session(backend="sdk", provider="deepseek-v4")
        session = db.get_session(sid)
        assert session["backend"] == "sdk"
        db.close()

    def test_list_sessions(self, db_path):
        from robocode.persistence.db import AuditDB

        db = AuditDB(db_path)
        db.initialize()
        db.create_session(backend="sdk")
        db.create_session(backend="ros2")
        sessions = db.list_sessions()
        assert len(sessions) >= 2
        db.close()


class TestToolCalls:
    def test_record_tool_call(self, db_path):
        from robocode.persistence.db import AuditDB

        db = AuditDB(db_path)
        db.initialize()
        sid = db.create_session(backend="sdk")
        db.record_tool_call(
            session_id=sid,
            tool_name="move_robot_xyz",
            risk_level="L2",
            params={"x": 300},
            result={"success": True},
            backend="sdk",
        )
        calls = db.list_tool_calls(sid)
        assert len(calls) == 1
        assert calls[0]["tool_name"] == "move_robot_xyz"
        db.close()


class TestApprovals:
    def test_record_approval(self, db_path):
        from robocode.persistence.db import AuditDB

        db = AuditDB(db_path)
        db.initialize()
        sid = db.create_session(backend="sdk")
        db.record_approval(
            session_id=sid,
            tool_name="move_robot_xyz",
            risk_level="L2",
            approved=True,
            rejected_by=None,
        )
        approvals = db.list_approvals(sid)
        assert len(approvals) == 1
        assert approvals[0]["approved"] == 1
        db.close()

    def test_rejected_approval(self, db_path):
        from robocode.persistence.db import AuditDB

        db = AuditDB(db_path)
        db.initialize()
        sid = db.create_session(backend="sdk")
        db.record_approval(
            session_id=sid, tool_name="t", risk_level="L2", approved=False, rejected_by="user"
        )
        approvals = db.list_approvals(sid)
        assert approvals[0]["approved"] == 0
        db.close()


class TestCheckpoints:
    def test_save_and_restore_checkpoint(self, db_path):
        from robocode.persistence.db import AuditDB

        db = AuditDB(db_path)
        db.initialize()
        sid = db.create_session(backend="sdk")
        db.save_checkpoint(
            session_id=sid,
            state="executing",
            task_plan={
                "steps": [{"name": "s1", "state": "success"}, {"name": "s2", "state": "pending"}]
            },
            step_index=1,
        )
        cp = db.get_latest_checkpoint(sid)
        assert cp is not None
        assert cp["state"] == "executing"
        assert cp["step_index"] == 1
        assert isinstance(cp["task_plan"], str)  # JSON string, consistent with other getters
        db.close()

    def test_no_checkpoint_returns_none(self, db_path):
        from robocode.persistence.db import AuditDB

        db = AuditDB(db_path)
        db.initialize()
        sid = db.create_session(backend="sdk")
        cp = db.get_latest_checkpoint(sid)
        assert cp is None
        db.close()
