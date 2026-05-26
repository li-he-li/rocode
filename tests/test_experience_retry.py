"""Tests for interrupt cleanup."""

from robocode.services.analytics.db import AuditDB


class TestInterruptCleanup:
    def make_db(self):
        db = AuditDB(":memory:")
        db.initialize()
        return db

    def test_cleanup_closes_session_preserves_physics(self):
        db = self.make_db()
        sid = db.create_session()

        call_id = db.record_tool_call(
            sid,
            "move_robot_xyz",
            "L2",
            {"x": 300},
            {"success": True},
        )
        db.insert_physics_data(
            tool_call_id=call_id,
            session_id=sid,
            tool_name="move_robot_xyz",
            joint_angles_before=[10, 20, 30, 40, 50, 60],
            joint_angles_after=[12, 22, 32, 42, 52, 62],
            duration_ms=3000,
            speed_ratio=0.5,
        )
        db.cleanup_interrupted_session(sid)
        session = db.list_sessions(limit=1)[0]
        assert session["status"] == "closed"
        physics = db.get_unprocessed_physics(sid)
        assert len(physics) == 1
        db.close()

    def test_cleanup_preserves_annotated_physics(self):
        db = self.make_db()
        sid = db.create_session()

        call_id = db.record_tool_call(
            sid,
            "move_robot_xyz",
            "L2",
            {"x": 300},
            {"success": True},
        )
        db.insert_physics_data(
            tool_call_id=call_id,
            session_id=sid,
            tool_name="move_robot_xyz",
            joint_angles_before=[10, 20, 30, 40, 50, 60],
            joint_angles_after=None,
            duration_ms=3000,
            speed_ratio=0.5,
        )
        db.insert_annotation(
            tool_call_id=call_id,
            session_id=sid,
            category="motion",
            choices={"motion_quality": "平稳"},
            is_failure=False,
        )

        db.cleanup_interrupted_session(sid)
        session = db.list_sessions(limit=1)[0]
        assert session["status"] == "closed"
        physics = db.get_unprocessed_physics(sid)
        assert len(physics) == 1
        db.close()
