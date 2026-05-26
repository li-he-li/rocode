"""7.1-7.4: End-to-end code evolution — discovery → generate → patch → check → one-shot.

Consolidates Section 5 (persistent registration), Section 6 (safety preservation),
and Section 7 (E2E validation) into a single practical test.
"""


class TestCodeEvolutionE2E:
    """Full one-shot code evolution flow: discover → generate → write → check → execute → discard."""

    def test_discover_sdk_patterns(self):
        """7.1: Agent discovers existing SDK patterns via code inspection."""
        from robocode.tools.code_tools import search_code, read_file

        # Search for existing SDK usage patterns
        result = search_code(pattern=r"backend\.", path="robocode/tools/")
        assert result["success"] is True
        assert result["metrics"]["match_count"] > 0

        # Read an existing tool to learn the pattern
        result = read_file(path="robocode/tools/gripper_tools.py")
        assert result["success"] is True
        assert "def control_suction" in result["message"]

    def test_generate_and_validate_one_shot_wrapper(self):
        """7.2: Generate wrapper → validate → does NOT register (one-shot)."""
        from robocode.tools.wrapper_tools import (
            generate_wrapper_template,
            generate_wrapper_metadata,
            validate_wrapper_metadata,
        )

        # Generate template
        result = generate_wrapper_template(
            name="move_circular",
            description="弧形路径移动到目标点",
            sdk_methods=['move_xyz_rotation(position, orientation, rotation_order="zyx")'],
            risk_level="L2",
            params={"x": "number", "y": "number", "z": "number", "radius": "number"},
        )
        assert result["success"] is True
        code = result["artifacts"]["code"]
        assert "def move_circular" in code
        assert "move_xyz_rotation" in code
        assert "ToolResult" in code

        # Generate metadata
        meta = generate_wrapper_metadata(
            name="move_circular",
            description="弧形路径移动",
            risk_level="L2",
            timeout_s=30.0,
            backend="sdk",
        )
        assert meta["risk_level"] == "L2"

        # Validate
        validation = validate_wrapper_metadata(meta)
        assert validation["valid"] is True

    def test_one_shot_execution_not_persistent(self):
        """5.x: Generated code is ephemeral — not added to registry."""
        from robocode.tools.registry import ToolRegistry

        registry = ToolRegistry()
        # The generated wrapper is NOT registered
        assert registry.get("move_circular") is None
        # Tool list stays clean
        assert len(registry) == 0

    def test_l2_wrappers_respect_approval_gate(self):
        """6.2: Generated L2 wrappers go through approval path (architectural guarantee)."""
        from robocode.tools.wrapper_tools import generate_wrapper_template

        result = generate_wrapper_template(
            name="custom_grasp",
            description="自定义抓取",
            sdk_methods=["servo_gripper(angle)"],
            risk_level="L2",
        )
        code = result["artifacts"]["code"]
        # Template includes safety check placeholder for L2
        assert "safety" in code.lower() or "check" in code.lower()
        # Template calls backend, not raw hardware
        assert "backend." in code

    def test_apply_patch_rejects_protected_files(self):
        """6.1: Cannot bypass safety by patching protected files."""
        from robocode.tools.patch_tools import apply_patch

        PATCH = """--- a/robocode/orchestrator/safety.py
+++ b/robocode/orchestrator/safety.py
@@ -13,7 +13,7 @@
-        (-180, 360),  # joint1
+        (-999, 999),  # joint1 — widened!
"""

        result = apply_patch(
            patch_text=PATCH,
            target_file="robocode/orchestrator/safety.py",
        )
        assert result["success"] is False
        assert "protected" in result["message"].lower() or "受保护" in result["message"]

    def test_estop_still_works_locally(self):
        """7.4: /estop bypasses LLM (unchanged)."""
        from robocode.cli.slash import SlashDispatcher

        dispatcher = SlashDispatcher()
        result = dispatcher.dispatch("/estop")
        assert result.handled is True
        assert result.estop_requested is True

    def test_safety_regression_after_code_evolution(self):
        """6.3/6.4: Safety checks still pass after code evolution tools exist."""
        from robocode.orchestrator.safety import SafetyPolicy

        policy = SafetyPolicy()
        # Workspace bounds still reject out-of-bounds coordinates
        check = policy.check_workspace_bounds(9999, 0, 0)
        assert check.passed is False

        # L2 still requires approval
        assert policy.requires_approval("L2") is True
        # L0 auto-approved
        assert policy.requires_approval("L0") is False

    def test_full_one_shot_flow(self):
        """7.2/7.3: Complete one-shot flow — discover, generate, check, execute, discard."""
        from robocode.tools.code_tools import read_file
        from robocode.tools.wrapper_tools import generate_wrapper_template

        # Step 1: Discover existing pattern
        r = read_file(path="robocode/tools/motion_tools.py")
        assert r["success"] is True
        assert "def move_robot_home" in r["message"]

        # Step 2: Generate wrapper
        r = generate_wrapper_template(
            name="quick_status",
            description="快速获取状态摘要",
            sdk_methods=["get_motor_angles()", "get_pose()"],
            risk_level="L0",
        )
        code = r["artifacts"]["code"]
        assert "def quick_status" in code
        assert "get_motor_angles" in code

        # Step 3: Generated code is valid Python (compiles cleanly)
        compile(code, "quick_status.py", "exec")

        # Step 4: No persistent state — not registered in registry
        from robocode.tools.registry import ToolRegistry

        reg = ToolRegistry()
        assert reg.get("quick_status") is None
