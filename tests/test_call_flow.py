"""Tests for call flow tracking in AgentLoop._execute_tool()."""

from robocode.services.analytics.db import AuditDB


class TestCallFlowTracking:
    """Test that task_instruction, turn_number, and prev_call_id are
    correctly recorded in tool_calls during a ReAct loop."""

    def make_db(self):
        db = AuditDB(":memory:")
        db.initialize()
        return db

    def test_same_instruction_same_task_context(self):
        """All calls under the same user instruction share task_instruction."""
        db = self.make_db()
        sid = db.create_session()

        instr = "抓取海绵块"
        c1 = db.record_tool_call(
            sid,
            "check_calibration_status",
            "L0",
            {},
            {"success": True},
            task_instruction=instr,
            turn_number=0,
            prev_call_id=None,
        )
        _ = db.record_tool_call(
            sid,
            "move_robot_xyz",
            "L2",
            {"x": 300},
            {"success": True},
            task_instruction=instr,
            turn_number=1,
            prev_call_id=c1,
        )

        rows = [
            dict(r)
            for r in db.conn.execute(
                "SELECT * FROM tool_calls WHERE session_id=? ORDER BY id", (sid,)
            ).fetchall()
        ]
        assert len(rows) == 2
        assert all(r["task_instruction"] == instr for r in rows)

    def test_turn_number_increments(self):
        db = self.make_db()
        sid = db.create_session()

        db.record_tool_call(
            sid,
            "get_robot_status",
            "L0",
            {},
            {"success": True},
            task_instruction="查看状态",
            turn_number=0,
        )
        _ = db.record_tool_call(
            sid,
            "move_robot_home",
            "L1",
            {},
            {"success": True},
            task_instruction="查看状态",
            turn_number=1,
        )
        rows = [
            dict(r)
            for r in db.conn.execute(
                "SELECT * FROM tool_calls WHERE session_id=? ORDER BY id", (sid,)
            ).fetchall()
        ]
        assert rows[0]["turn_number"] == 0
        assert rows[1]["turn_number"] == 1

    def test_prev_call_id_chain(self):
        db = self.make_db()
        sid = db.create_session()

        c1 = db.record_tool_call(
            sid,
            "check_calibration_status",
            "L0",
            {},
            {"success": True},
            task_instruction="抓取",
            turn_number=0,
            prev_call_id=None,
        )
        c2 = db.record_tool_call(
            sid,
            "move_robot_xyz",
            "L2",
            {"x": 300},
            {"success": True},
            task_instruction="抓取",
            turn_number=1,
            prev_call_id=c1,
        )
        db.record_tool_call(
            sid,
            "6d_grasp",
            "L2",
            {"instruction": "抓取"},
            {"success": True},
            task_instruction="抓取",
            turn_number=2,
            prev_call_id=c2,
        )

        rows = [
            dict(r)
            for r in db.conn.execute(
                "SELECT * FROM tool_calls WHERE session_id=? ORDER BY id", (sid,)
            ).fetchall()
        ]
        assert rows[0]["prev_call_id"] is None
        assert rows[1]["prev_call_id"] == c1
        assert rows[2]["prev_call_id"] == c2

    def test_different_instructions_isolated(self):
        """Calls under different instructions are isolated."""
        db = self.make_db()
        sid = db.create_session()

        db.record_tool_call(
            sid,
            "move_robot_home",
            "L1",
            {},
            {"success": True},
            task_instruction="移动到观察位",
            turn_number=0,
            prev_call_id=None,
        )
        c2 = db.record_tool_call(
            sid,
            "get_robot_status",
            "L0",
            {},
            {"success": True},
            task_instruction="抓取海绵块",
            turn_number=0,
            prev_call_id=None,
        )
        _ = db.record_tool_call(
            sid,
            "move_robot_xyz",
            "L2",
            {"x": 300},
            {"success": True},
            task_instruction="抓取海绵块",
            turn_number=1,
            prev_call_id=c2,
        )

        rows = [
            dict(r)
            for r in db.conn.execute(
                "SELECT * FROM tool_calls WHERE session_id=? ORDER BY id", (sid,)
            ).fetchall()
        ]
        assert rows[0]["task_instruction"] == "移动到观察位"
        assert rows[0]["turn_number"] == 0
        assert rows[0]["prev_call_id"] is None
        assert rows[1]["task_instruction"] == "抓取海绵块"
        assert rows[1]["turn_number"] == 0
        assert rows[1]["prev_call_id"] is None
        assert rows[2]["task_instruction"] == "抓取海绵块"
        assert rows[2]["turn_number"] == 1
        assert rows[2]["prev_call_id"] == c2

    def test_call_flow_backward_compatible(self):
        """record_tool_call without call flow fields still works."""
        db = self.make_db()
        sid = db.create_session()
        cid = db.record_tool_call(
            sid,
            "get_robot_status",
            "L0",
            {},
            {"success": True},
        )
        assert isinstance(cid, int)
        row = dict(db.conn.execute("SELECT * FROM tool_calls WHERE id=?", (cid,)).fetchone())
        assert row["task_instruction"] is None
        assert row["turn_number"] is None
        assert row["prev_call_id"] is None
