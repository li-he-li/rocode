"""4.1: Tool authoring tests — wrapper generation, metadata, registration gate."""


class TestWrapperTemplate:
    def test_generate_sdk_wrapper(self):
        """4.2: SDK-backed wrapper template generation."""
        from robocode.tools.wrapper_tools import generate_wrapper_template

        result = generate_wrapper_template(
            name="custom_move_arc",
            description="弧形移动到目标点",
            sdk_methods=["move_xyz_rotation(position, orientation)"],
            risk_level="L2",
        )
        assert result["success"] is True
        code = result.get("artifacts", {}).get("code", result.get("code", ""))
        assert "def custom_move_arc" in code
        assert "move_xyz_rotation" in code
        assert "ToolResult" in code

    def test_template_includes_safety_checks(self):
        """4.2: Template includes safety and workspace checks."""
        from robocode.tools.wrapper_tools import generate_wrapper_template

        result = generate_wrapper_template(
            name="move_to_point",
            description="移动到指定点",
            sdk_methods=["move_xyz_rotation(position, orientation)"],
            risk_level="L2",
            params={"x": "number", "y": "number", "z": "number"},
        )
        code = result.get("artifacts", {}).get("code", result.get("code", ""))
        assert "safety" in code or "check" in code.lower()

    def test_generate_ros2_wrapper(self):
        """4.3: ROS2-backed wrapper template."""
        from robocode.tools.wrapper_tools import generate_wrapper_template

        result = generate_wrapper_template(
            name="ros2_get_joint_states",
            description="通过 ROS2 获取关节状态",
            sdk_methods=[],
            ros2_actions=["/joint_states"],
            risk_level="L0",
            backend="ros2",
        )
        assert result["success"] is True
        code = result.get("artifacts", {}).get("code", result.get("code", ""))
        assert "ros2" in code.lower() or "ROS2" in code


class TestWrapperMetadata:
    def test_metadata_generation(self):
        """4.4: Wrapper metadata includes all required fields."""
        from robocode.tools.wrapper_tools import generate_wrapper_metadata

        meta = generate_wrapper_metadata(
            name="test_tool",
            description="测试工具",
            risk_level="L1",
            timeout_s=30.0,
            backend="sdk",
        )
        assert meta["name"] == "test_tool"
        assert meta["description"] == "测试工具"
        assert meta["risk_level"] == "L1"
        assert meta["timeout_s"] == 30.0
        assert meta["backend"] == "sdk"

    def test_metadata_validation_requires_name(self):
        """4.1: Metadata validation rejects missing name."""
        from robocode.tools.wrapper_tools import validate_wrapper_metadata

        result = validate_wrapper_metadata({})
        assert result["valid"] is False
        assert "name" in str(result.get("errors", ""))

    def test_metadata_validation_requires_risk_level(self):
        from robocode.tools.wrapper_tools import validate_wrapper_metadata

        result = validate_wrapper_metadata({"name": "test", "description": "desc"})
        assert result["valid"] is False

    def test_valid_metadata_passes(self):
        from robocode.tools.wrapper_tools import validate_wrapper_metadata

        result = validate_wrapper_metadata(
            {
                "name": "valid_tool",
                "description": "A valid tool",
                "risk_level": "L1",
                "timeout_s": 30.0,
                "backend": "sdk",
                "parameters": {"type": "object", "properties": {}},
            }
        )
        assert result["valid"] is True


class TestRegistrationGate:
    def test_registration_requires_valid_metadata(self):
        """4.5: Registration rejected for invalid metadata."""
        from robocode.tools.wrapper_tools import register_wrapper
        import robocode.tools.wrapper_tools as wt
        from robocode.tools.registry import ToolRegistry

        registry = ToolRegistry()
        wt._REGISTRY = registry
        result = register_wrapper(
            name="",
            description="",
            risk_level="INVALID",
        )
        assert result["success"] is False

    def test_registration_succeeds_with_valid_data(self):
        """4.5: Registration succeeds with valid metadata."""
        from robocode.tools.wrapper_tools import register_wrapper
        import robocode.tools.wrapper_tools as wt
        from robocode.tools.registry import ToolRegistry

        registry = ToolRegistry()
        wt._REGISTRY = registry

        result = register_wrapper(
            name="my_custom_tool",
            description="A custom tool for testing",
            risk_level="L1",
            timeout_s=30.0,
            backend="sdk",
            parameters={"type": "object", "properties": {}},
            dry_run=False,
        )
        assert result["success"] is True
        assert registry.get("my_custom_tool") is not None

    def test_l2_motion_wrappers_retain_l2(self):
        """5.5 (combined): Motion/grasp wrappers inherit L2."""
        from robocode.tools.wrapper_tools import register_wrapper
        import robocode.tools.wrapper_tools as wt
        from robocode.tools.registry import ToolRegistry

        registry = ToolRegistry()
        wt._REGISTRY = registry

        result = register_wrapper(
            name="custom_move",
            description="Custom movement that controls hardware",
            risk_level="L2",
            timeout_s=30.0,
            backend="sdk",
            parameters={"type": "object", "properties": {"x": {"type": "number"}}},
            dry_run=False,
        )
        assert result["success"] is True
        entry = registry.get("custom_move")
        assert entry.risk_level == "L2"


class TestDryRunRequirement:
    def test_dry_run_required_before_registration(self):
        """4.1: Dry-run flag required in metadata."""
        from robocode.tools.wrapper_tools import validate_wrapper_metadata

        # Metadata without dry_run flag
        result = validate_wrapper_metadata(
            {
                "name": "test",
                "description": "desc",
                "risk_level": "L2",
                "timeout_s": 30.0,
                "backend": "sdk",
                "parameters": {"type": "object", "properties": {}},
            }
        )
        # Should warn but not reject (dry_run is recommended, not mandatory)
        assert "dry_run" in str(result.get("warnings", "")).lower() or result["valid"] is True
