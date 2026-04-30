"""Motion and status tools — wrapped SDK calls with safety checks."""

from robocode.backends.base import RobotBackend
from robocode.orchestrator.safety import SafetyPolicy
from robocode.utils.models import ToolResult


def make_motion_tools(backend: RobotBackend, safety: SafetyPolicy) -> dict:
    def get_robot_status(**kwargs):
        s = backend.get_status()
        return ToolResult(
            success=s.connected,
            message="机器人在线" if s.connected else "机器人离线",
            metrics={
                "angles": s.motor_angles,
                "pose": s.pose,
                "estop_active": s.estop_active,
                "backend": s.backend,
            },
        ).model_dump(mode="json")

    def move_robot_home(**kwargs):
        checks = safety.check_operation(
            "move_robot_home",
            {
                "x": 260.0,
                "y": 0.0,
                "z": 200.0,
            },
        )
        failed = [c for c in checks if not c.passed]
        if failed:
            return ToolResult(success=False, message=failed[0].reason).model_dump(mode="json")
        result = backend.move_xyz_rotation([260.0, 0.0, 200.0], [180.0, 0.0, 90.0])
        if result < 0:
            return ToolResult(success=False, message="IK 无解，回零位失败").model_dump(mode="json")
        return ToolResult(success=True, message=f"已回零位，耗时 {result:.1f}s").model_dump(
            mode="json"
        )

    def move_robot_xyz(*, x, y, z, speed_ratio=0.5, rotation=(180, 0, 90), **kwargs):
        checks = safety.check_operation(
            "move_robot_xyz",
            {
                "x": x,
                "y": y,
                "z": z,
                "speed_ratio": speed_ratio,
            },
        )
        failed = [c for c in checks if not c.passed]
        if failed:
            return ToolResult(success=False, message=failed[0].reason).model_dump(mode="json")
        result = backend.move_xyz_rotation(
            [float(x), float(y), float(z)],
            [float(r) for r in rotation],
            speed_ratio=float(speed_ratio),
        )
        if result < 0:
            return ToolResult(success=False, message="IK 无解").model_dump(mode="json")
        return ToolResult(
            success=True, message=f"移动到 ({x},{y},{z}), 耗时 {result:.1f}s"
        ).model_dump(mode="json")

    def move_robot_joints(*, angles, speed_ratio=0.5, **kwargs):
        angles = [float(a) for a in angles]
        joint_check = safety.check_joint_limits(angles)
        if not joint_check.passed:
            return ToolResult(success=False, message=joint_check.reason).model_dump(mode="json")
        speed_check = safety.check_speed(float(speed_ratio))
        if not speed_check.passed:
            return ToolResult(success=False, message=speed_check.reason).model_dump(mode="json")
        result = backend.angle_mode(angles, float(speed_ratio))
        if result < 0:
            return ToolResult(success=False, message="关节运动失败").model_dump(mode="json")
        return ToolResult(success=True, message=f"关节运动完成, 耗时 {result:.1f}s").model_dump(
            mode="json"
        )

    def emergency_stop(*, enable, **kwargs):
        if not isinstance(enable, (bool, int)):
            return ToolResult(success=False, message="enable 必须为 bool 或 int").model_dump(
                mode="json"
            )
        enable_bool = bool(enable)
        backend.emergency_stop(enable_bool)
        action = "已急停" if enable_bool else "已解除急停"
        return ToolResult(success=True, message=action).model_dump(mode="json")

    return {
        "get_robot_status": get_robot_status,
        "move_robot_home": move_robot_home,
        "move_robot_xyz": move_robot_xyz,
        "move_robot_joints": move_robot_joints,
        "emergency_stop": emergency_stop,
    }
