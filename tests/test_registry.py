"""Tool registry tests — registration, schema validation, skills, unknown tool rejection."""

import pytest
from robocode.tools.registry import ToolRegistry, ToolEntry, SkillEntry


class TestToolEntry:
    def test_create_tool_entry(self):
        entry = ToolEntry(
            name="move_robot_xyz",
            description="移动到指定坐标",
            parameters={
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"},
                },
                "required": ["x", "y", "z"],
            },
            risk_level="L2",
            timeout_s=30.0,
        )
        assert entry.name == "move_robot_xyz"
        assert entry.risk_level == "L2"
        assert entry.timeout_s == 30.0

    def test_to_openai_schema(self):
        entry = ToolEntry(
            name="get_robot_status",
            description="获取机器人状态",
            parameters={"type": "object", "properties": {}},
            risk_level="L0",
        )
        schema = entry.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "get_robot_status"


class TestSkillEntry:
    def test_create_skill(self):
        skill = SkillEntry(
            name="hand_eye_calibration",
            description="执行手眼标定（需人在 GUI 操作）",
            parameters={"type": "object", "properties": {}},
            script_path="calibration_scripts/4.calibrate_hand_eye_qt_ros2.py",
            requires_human=True,
            output_files=["hand_eye_calibration.yaml"],
            risk_level="L1",
        )
        assert skill.is_skill is True
        assert skill.script_path.endswith(".py")
        assert skill.requires_human is True

    def test_skill_to_openai_schema(self):
        skill = SkillEntry(
            name="hand_eye_calibration",
            description="手眼标定",
            parameters={"type": "object", "properties": {}},
            script_path="cal.py",
            requires_human=True,
            output_files=["result.yaml"],
            risk_level="L1",
        )
        schema = skill.to_openai_schema()
        assert schema["function"]["name"] == "hand_eye_calibration"
        assert schema["function"]["description"] == "手眼标定"


class TestToolRegistry:
    def test_register_and_get_tool(self):
        reg = ToolRegistry()
        entry = ToolEntry(
            name="test_tool",
            description="a test tool",
            parameters={"type": "object", "properties": {}},
            risk_level="L0",
        )
        reg.register(entry)
        assert reg.get("test_tool") is entry
        assert reg.get("nonexistent") is None

    def test_register_and_get_skill(self):
        reg = ToolRegistry()
        skill = SkillEntry(
            name="calibration_skill",
            description="标定",
            parameters={"type": "object", "properties": {}},
            script_path="cal.py",
            requires_human=True,
            output_files=["cal.yaml"],
            risk_level="L1",
        )
        reg.register(skill)
        assert reg.get("calibration_skill") is skill
        assert reg.get("calibration_skill").is_skill is True

    def test_list_tools_excludes_skills(self):
        reg = ToolRegistry()
        reg.register(ToolEntry(name="t1", description="", parameters={}, risk_level="L0"))
        reg.register(
            SkillEntry(
                name="s1",
                description="",
                parameters={},
                script_path="s.py",
                requires_human=False,
                output_files=[],
                risk_level="L1",
            )
        )
        tools = reg.list_tools()
        assert len([t for t in tools if t.is_skill]) == 0

    def test_list_skills(self):
        reg = ToolRegistry()
        reg.register(
            SkillEntry(
                name="s1",
                description="s",
                parameters={},
                script_path="a.py",
                requires_human=False,
                output_files=[],
                risk_level="L1",
            )
        )
        reg.register(
            SkillEntry(
                name="s2",
                description="s",
                parameters={},
                script_path="b.py",
                requires_human=True,
                output_files=[],
                risk_level="L2",
            )
        )
        assert len(reg.list_skills()) == 2

    def test_list_skills_returns_empty_list(self):
        reg = ToolRegistry()
        assert reg.list_skills() == []

    def test_all_schemas(self):
        reg = ToolRegistry()
        reg.register(ToolEntry(name="t1", description="d1", parameters={}, risk_level="L0"))
        reg.register(
            SkillEntry(
                name="s1",
                description="d2",
                parameters={},
                script_path="x.py",
                requires_human=True,
                output_files=[],
                risk_level="L1",
            )
        )
        schemas = reg.all_schemas()
        assert len(schemas) == 2

    def test_duplicate_registration_raises(self):
        reg = ToolRegistry()
        reg.register(ToolEntry(name="t1", description="d", parameters={}, risk_level="L0"))
        with pytest.raises(ValueError):
            reg.register(ToolEntry(name="t1", description="d2", parameters={}, risk_level="L0"))

    def test_risk_filter(self):
        reg = ToolRegistry()
        reg.register(ToolEntry(name="t0", description="", parameters={}, risk_level="L0"))
        reg.register(ToolEntry(name="t2", description="", parameters={}, risk_level="L2"))
        l0 = reg.filter_by_risk("L0")
        assert len(l0) == 1
        assert l0[0].name == "t0"
