"""Tests for experience evolution DB schema migration and CRUD operations."""

import json
from robocode.services.analytics.db import AuditDB


class TestToolPhysicsDataCRUD:
    def test_insert_and_query_physics_data(self):
        db = AuditDB(":memory:")
        db.initialize()
        sid = db.create_session()

        call_id = db.record_tool_call(
            sid,
            "move_robot_xyz",
            "L2",
            {"x": 300, "y": 0, "z": 200},
            {"success": True},
            duration_ms=3200,
        )
        assert isinstance(call_id, int)

        db.insert_physics_data(
            tool_call_id=call_id,
            session_id=sid,
            tool_name="move_robot_xyz",
            joint_angles_before=[10, 20, 30, 40, 50, 60],
            joint_angles_after=[12, 22, 32, 42, 52, 62],
            duration_ms=3200,
            speed_ratio=0.5,
        )

        rows = db.get_unprocessed_physics(sid)
        assert len(rows) == 1
        r = rows[0]
        assert r["tool_call_id"] == call_id
        assert r["tool_name"] == "move_robot_xyz"
        assert json.loads(r["joint_angles_before"]) == [10, 20, 30, 40, 50, 60]
        assert json.loads(r["joint_angles_after"]) == [12, 22, 32, 42, 52, 62]
        assert r["duration_ms"] == 3200
        assert r["speed_ratio"] == 0.5
        assert "end_pose_before" not in r.keys()
        assert "end_pose_after" not in r.keys()
        assert "payload_kg" not in r.keys()

        db.close()

    def test_insert_physics_no_after_snapshot(self):
        """Physics data can be written even when after-snapshot fails."""
        db = AuditDB(":memory:")
        db.initialize()
        sid = db.create_session()
        call_id = db.record_tool_call(
            sid,
            "move_robot_joints",
            "L2",
            {"angles": [10, 20, 30, 40, 50, 60]},
            {"success": False},
        )
        db.insert_physics_data(
            tool_call_id=call_id,
            session_id=sid,
            tool_name="move_robot_joints",
            joint_angles_before=[10, 20, 30, 40, 50, 60],
            joint_angles_after=None,
            duration_ms=500,
            speed_ratio=0.3,
        )
        rows = db.get_unprocessed_physics(sid)
        assert len(rows) == 1
        assert rows[0]["joint_angles_after"] is None
        db.close()


class TestToolAnnotationsCRUD:
    def test_insert_and_query_annotation(self):
        db = AuditDB(":memory:")
        db.initialize()
        sid = db.create_session()
        call_id = db.record_tool_call(
            sid,
            "move_robot_xyz",
            "L2",
            {"x": 300},
            {"success": True},
        )
        db.insert_annotation(
            tool_call_id=call_id,
            session_id=sid,
            category="motion",
            choices={"motion_quality": "平稳", "position_accuracy": "准确"},
            is_failure=False,
            free_text="运行很顺畅",
        )
        rows = db.get_unprocessed_annotations(sid)
        assert isinstance(rows, list)
        assert len(rows) >= 1

        found = [r for r in rows if r["tool_call_id"] == call_id]
        assert len(found) == 1
        a = found[0]
        assert a["category"] == "motion"
        assert json.loads(a["choices"]) == {"motion_quality": "平稳", "position_accuracy": "准确"}
        assert a["is_failure"] == 0
        assert a["free_text"] == "运行很顺畅"
        db.close()

    def test_insert_failure_annotation(self):
        db = AuditDB(":memory:")
        db.initialize()
        sid = db.create_session()
        call_id = db.record_tool_call(
            sid,
            "6d_grasp",
            "L2",
            {"instruction": "抓取海绵块"},
            {"success": False},
        )
        db.insert_annotation(
            tool_call_id=call_id,
            session_id=sid,
            category="grasp",
            choices={"grasp_result": "未命中", "overall": "失败"},
            is_failure=True,
        )
        rows = db.get_unprocessed_annotations(sid)
        found = [r for r in rows if r["tool_call_id"] == call_id]
        assert found[0]["is_failure"] == 1
        db.close()


class TestExperienceLogWrite:
    def test_write_experience_log(self):
        db = AuditDB(":memory:")
        db.initialize()

        db.insert_experience_log(
            "created",
            "physics/angle-deviation.md",
            {"domain": "velocity", "confidence": 0.85},
        )
        db.insert_experience_log(
            "updated",
            "grasp/grasp-6d.md",
            {"confidence_delta": 0.1},
        )
        db.insert_experience_log(
            "merged",
            "motion/merged-vibration.md",
            {"source_files": ["motion/a.md", "motion/b.md"]},
        )

        rows = db.conn.execute("SELECT * FROM experience_log ORDER BY created_at").fetchall()
        assert len(rows) == 3
        events = [dict(r)["event_type"] for r in rows]
        assert events == ["created", "updated", "merged"]

        merge_detail = json.loads(dict(rows[2])["details"])
        assert merge_detail["source_files"] == ["motion/a.md", "motion/b.md"]
        db.close()


class TestAutoMigration:
    def test_alter_tool_calls_idempotent(self):
        """ALTER TABLE should be idempotent — no error on second call."""
        db = AuditDB(":memory:")
        db.initialize()
        cols_before = {
            row["name"] for row in db.conn.execute("PRAGMA table_info(tool_calls)").fetchall()
        }
        for col in (
            "physics_captured",
            "annotated",
            "task_instruction",
            "turn_number",
            "prev_call_id",
        ):
            assert col in cols_before, f"Column {col} missing from tool_calls"

        db._auto_migrate()
        db._auto_migrate()
        cols_after = {
            row["name"] for row in db.conn.execute("PRAGMA table_info(tool_calls)").fetchall()
        }
        assert cols_before == cols_after
        db.close()

    def test_record_tool_call_accepts_new_fields(self):
        db = AuditDB(":memory:")
        db.initialize()
        sid = db.create_session()

        call_id = db.record_tool_call(
            sid,
            "get_robot_status",
            "L0",
            {},
            {"connected": True},
            duration_ms=10,
            task_instruction="查看状态",
            turn_number=0,
            prev_call_id=None,
        )
        assert isinstance(call_id, int)

        row = dict(db.conn.execute("SELECT * FROM tool_calls WHERE id=?", (call_id,)).fetchone())
        assert row["task_instruction"] == "查看状态"
        assert row["turn_number"] == 0
        assert row["prev_call_id"] is None
        assert row["physics_captured"] == 0
        assert row["annotated"] == 0
        db.close()

    def test_record_tool_call_call_chain(self):
        db = AuditDB(":memory:")
        db.initialize()
        sid = db.create_session()

        c1 = db.record_tool_call(
            sid,
            "check_calibration_status",
            "L0",
            {},
            {"success": True},
            task_instruction="抓取海绵块",
            turn_number=0,
            prev_call_id=None,
        )
        c2 = db.record_tool_call(
            sid,
            "move_robot_xyz",
            "L2",
            {"x": 300},
            {"success": True},
            task_instruction="抓取海绵块",
            turn_number=1,
            prev_call_id=c1,
        )
        db.record_tool_call(
            sid,
            "6d_grasp",
            "L2",
            {"instruction": "抓取海绵块"},
            {"success": True},
            task_instruction="抓取海绵块",
            turn_number=2,
            prev_call_id=c2,
        )

        rows = [
            dict(r)
            for r in db.conn.execute(
                "SELECT * FROM tool_calls WHERE session_id=? ORDER BY id", (sid,)
            )
        ]
        assert rows[0]["task_instruction"] == "抓取海绵块"
        assert rows[0]["turn_number"] == 0
        assert rows[0]["prev_call_id"] is None

        assert rows[1]["task_instruction"] == "抓取海绵块"
        assert rows[1]["turn_number"] == 1
        assert rows[1]["prev_call_id"] == c1

        assert rows[2]["task_instruction"] == "抓取海绵块"
        assert rows[2]["turn_number"] == 2
        assert rows[2]["prev_call_id"] == c2

        db.close()

    def test_record_tool_call_backward_compatible(self):
        """record_tool_call without new fields should still work."""
        db = AuditDB(":memory:")
        db.initialize()
        sid = db.create_session()
        call_id = db.record_tool_call(
            sid,
            "get_robot_status",
            "L0",
            {},
            {"connected": True},
            duration_ms=10,
        )
        assert isinstance(call_id, int)
        row = dict(db.conn.execute("SELECT * FROM tool_calls WHERE id=?", (call_id,)).fetchone())
        assert row["task_instruction"] is None
        assert row["turn_number"] is None
        assert row["physics_captured"] == 0
        assert row["annotated"] == 0
        db.close()
