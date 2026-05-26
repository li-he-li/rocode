"""Robot tools tests — motion, gripper, grasp, script tools with fake backend."""

from robocode.tools.motion_tools import make_motion_tools
from robocode.tools.gripper_tools import make_gripper_tools
from robocode.tools.script_tools import make_script_tools
from robocode.backends.sdk_backend import FakeEpisodeAPP, SdkBackend, EpisodeVariant
from robocode.orchestrator.safety import SafetyPolicy
from robocode.utils.models import ToolResult


def make_fake_backend():
    return SdkBackend(client=FakeEpisodeAPP(), variant=EpisodeVariant.SDK)


class TestMotionTools:
    def setup_method(self):
        self.backend = make_fake_backend()
        self.safety = SafetyPolicy()
        self.tools = make_motion_tools(self.backend, self.safety)

    def test_get_robot_status(self):
        result = self.tools["get_robot_status"]()
        r = ToolResult(**result)
        assert r.success is True
        assert "angles" in r.metrics
        assert len(r.metrics["angles"]) == 6

    def test_move_robot_home(self):
        result = self.tools["move_robot_home"]()
        r = ToolResult(**result)
        assert r.success is True
        assert "回零" in r.message

    def test_move_robot_xyz_valid(self):
        result = self.tools["move_robot_xyz"](x=300, y=0, z=200, speed_ratio=0.5)
        r = ToolResult(**result)
        assert r.success is True

    def test_move_robot_xyz_out_of_bounds(self):
        result = self.tools["move_robot_xyz"](x=1000, y=0, z=200, speed_ratio=0.5)
        r = ToolResult(**result)
        assert r.success is False
        assert "超出" in r.message or "越界" in r.message or "工作空间" in r.message

    def test_move_robot_joints_valid(self):
        result = self.tools["move_robot_joints"](angles=[180, 90, 83, 30, 110, 30], speed_ratio=0.5)
        r = ToolResult(**result)
        assert r.success is True

    def test_move_robot_joints_oob(self):
        result = self.tools["move_robot_joints"](angles=[999, 0, 0, 0, 0, 0], speed_ratio=0.5)
        r = ToolResult(**result)
        assert r.success is False

    def test_move_robot_home_safety_reject(self):
        # Force safety to reject by setting an impossibly small workspace
        self.safety.settings.workspace.x_max = 0.0
        result = self.tools["move_robot_home"]()
        assert result["success"] is False

    def test_estop(self):
        result = self.tools["emergency_stop"]()
        assert result["success"] is True

    def test_estop_release(self):
        result = self.tools["release_emergency_stop"]()
        assert result["success"] is True


class TestGripperTools:
    def setup_method(self):
        self.backend = make_fake_backend()
        self.safety = SafetyPolicy()
        self.tools = make_gripper_tools(self.backend, self.safety)

    def test_control_suction_on(self):
        result = self.tools["control_suction"](action="on")
        assert result["success"] is True

    def test_control_suction_off(self):
        result = self.tools["control_suction"](action="off")
        assert result["success"] is True

    def test_control_suction_invalid_action(self):
        result = self.tools["control_suction"](action="toggle")
        assert result["success"] is False

    def test_servo_gripper_valid(self):
        result = self.tools["servo_gripper_control"](angle=45)
        assert result["success"] is True

    def test_servo_gripper_oob(self):
        result = self.tools["servo_gripper_control"](angle=200)
        assert result["success"] is False


class TestScriptTools:
    def setup_method(self):
        self.tools = make_script_tools()

    def test_check_calibration_status(self):
        result = self.tools["check_calibration_status"](calib_type="hand_eye")
        # hand_eye_calibration.yaml exists in the target project
        assert result["success"] is True
        assert result["metrics"]["T_matrix_available"] is True
