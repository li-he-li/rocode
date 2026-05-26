"""Tests for annotation system — TOOL_CATEGORIES, AnnotationResult, AnnotationCollector."""

import json
from robocode.agent.annotation import (
    TOOL_CATEGORIES,
    AnnotationResult,
    AnnotationCollector,
)


class TestToolCategoriesMapping:
    def test_motion_tools_in_category(self):
        assert TOOL_CATEGORIES["move_robot_xyz"] == "motion"
        assert TOOL_CATEGORIES["move_robot_joints"] == "motion"
        assert TOOL_CATEGORIES["move_robot_home"] == "motion"
        assert TOOL_CATEGORIES["move_path"] == "motion"

    def test_gripper_tools_in_category(self):
        assert TOOL_CATEGORIES["control_suction"] == "gripper"
        assert TOOL_CATEGORIES["servo_gripper_control"] == "gripper"

    def test_grasp_tools_in_category(self):
        assert TOOL_CATEGORIES["6d_grasp"] == "grasp"
        assert TOOL_CATEGORIES["run_script"] == "script"

    def test_code_tools_in_category(self):
        assert TOOL_CATEGORIES["generate_and_run_sdk_code"] == "code"
        assert TOOL_CATEGORIES["execute_command"] == "code"

    def test_unknown_tool_defaults_to_general(self):
        assert TOOL_CATEGORIES.get("unknown_tool", "general") == "general"


class TestAnnotationResult:
    def test_serialization(self):
        result = AnnotationResult(
            tool_call_id=42,
            tool_name="move_robot_xyz",
            category="motion",
            choices={"feedback": "运动平稳"},
            is_failure=False,
            free_text="运动平稳，位置准确",
        )
        data = result.to_dict()
        assert data["tool_call_id"] == 42
        assert data["tool_name"] == "move_robot_xyz"
        assert data["category"] == "motion"
        assert data["is_failure"] is False
        assert data["free_text"] == "运动平稳，位置准确"

    def test_failure_result(self):
        result = AnnotationResult(
            tool_call_id=7,
            tool_name="6d_grasp",
            category="grasp",
            choices={"feedback": "没抓到"},
            is_failure=True,
            free_text="没抓到物体，偏差很大",
        )
        data = result.to_dict()
        assert data["is_failure"] is True
        assert "没抓到" in data["free_text"]
        assert json.dumps(data["choices"])


class FakeDB:
    def __init__(self):
        self.annotations = []

    def insert_annotation(
        self, tool_call_id, session_id, category, choices, is_failure, free_text=""
    ):
        self.annotations.append(
            {
                "tool_call_id": tool_call_id,
                "session_id": session_id,
                "category": category,
                "choices": choices,
                "is_failure": is_failure,
                "free_text": free_text,
            }
        )


class TestAnnotationCollector:
    def make_collector(self):
        db = FakeDB()
        collector = AnnotationCollector(db=db, session_id="sess-01")
        return collector, db

    def test_register_and_get_pending(self):
        collector, _ = self.make_collector()
        collector.register_tool_call(1, "move_robot_xyz", {"x": 300, "y": 0, "z": 200})
        collector.register_tool_call(2, "control_suction", {"action": "on"})
        pending = collector.get_pending()
        assert len(pending) == 2
        assert pending[0]["tool_name"] == "move_robot_xyz"
        assert pending[1]["tool_name"] == "control_suction"

    def test_collect_writes_annotation(self):
        collector, db = self.make_collector()
        collector.register_tool_call(1, "move_robot_xyz", {"x": 300})
        result = collector.collect(
            tool_call_id=1,
            category="motion",
            choices={"feedback": "运动平稳"},
            is_failure=False,
            free_text="运动平稳",
        )
        assert result is not None
        assert len(db.annotations) == 1

    def test_collect_marks_annotated(self):
        collector, db = self.make_collector()
        collector.register_tool_call(1, "move_robot_xyz", {"x": 300})
        collector.collect(1, "motion", {"feedback": "平稳"}, False)
        pending = collector.get_pending()
        assert len(pending) == 0

    def test_skip_removes_from_pending(self):
        collector, _ = self.make_collector()
        collector.register_tool_call(1, "move_robot_xyz", {"x": 300})
        collector.skip(1)
        pending = collector.get_pending()
        assert len(pending) == 0

    def test_count_unannotated(self):
        collector, _ = self.make_collector()
        collector.register_tool_call(1, "move_robot_xyz", {"x": 300})
        collector.register_tool_call(2, "control_suction", {"action": "on"})
        assert collector.count_unannotated() == 2
        collector.collect(1, "motion", {"feedback": "平稳"}, False)
        assert collector.count_unannotated() == 1

    def test_get_category_for_tool(self):
        collector, _ = self.make_collector()
        assert collector.get_category("move_robot_xyz") == "motion"
        assert collector.get_category("6d_grasp") == "grasp"
        assert collector.get_category("unknown_tool") == "general"
