"""Motion and status tools — wrapped SDK calls with safety checks."""

from robocode.backends.base import RobotBackend
from robocode.orchestrator.safety import SafetyPolicy
from robocode.utils.models import ToolResult


def make_motion_tools(backend: RobotBackend, safety: SafetyPolicy) -> dict:
    _is_fake = getattr(backend, "is_fake", False)

    def _dry(msg: str) -> str:
        return f"[DRY-RUN] {msg}" if _is_fake else msg

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
        return ToolResult(success=True, message=_dry(f"已回零位，耗时 {result:.1f}s")).model_dump(
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
            success=True, message=_dry(f"移动到 ({x},{y},{z}), 耗时 {result:.1f}s")
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
        return ToolResult(
            success=True, message=_dry(f"关节运动完成, 耗时 {result:.1f}s")
        ).model_dump(mode="json")

    def move_path(*, waypoints, speed_ratio=0.5, rotation=(180, 0, 90), **kwargs):
        """Execute a continuous path through multiple waypoints using linear moves.

        Args:
            waypoints: list of [x, y, z] positions in mm
            speed_ratio: speed factor 0.0-1.0
            rotation: end-effector orientation [rx, ry, rz] in degrees
        """
        if not waypoints:
            return ToolResult(success=False, message="waypoints 为空").model_dump(mode="json")
        if len(waypoints) > 200:
            return ToolResult(
                success=False, message=f"路点过多 ({len(waypoints)} > 200)"
            ).model_dump(mode="json")

        rot = [float(r) for r in rotation]
        sr = float(speed_ratio)
        total_time = 0.0
        errors = []

        for i, wp in enumerate(waypoints):
            if len(wp) != 3:
                errors.append(f"路点[{i}] 需要 [x,y,z]")
                continue
            x, y, z = float(wp[0]), float(wp[1]), float(wp[2])

            checks = safety.check_operation(
                "move_path", {"x": x, "y": y, "z": z, "speed_ratio": sr}
            )
            failed = [c for c in checks if not c.passed]
            if failed:
                errors.append(f"路点[{i}] ({x:.1f},{y:.1f},{z:.1f}): {failed[0].reason}")
                continue

            result = backend.move_linear_xyz_rotation([x, y, z], rot, speed_ratio=sr)
            if result < 0:
                errors.append(f"路点[{i}] ({x:.1f},{y:.1f},{z:.1f}): IK 无解")
            else:
                total_time += result

        if errors:
            return ToolResult(
                success=len(errors) < len(waypoints),
                message=_dry(
                    f"路径完成 {len(waypoints) - len(errors)}/{len(waypoints)} 点, 错误: {'; '.join(errors[:3])}"
                ),
            ).model_dump(mode="json")

        return ToolResult(
            success=True,
            message=_dry(f"连续路径完成, {len(waypoints)} 点, 总耗时 {total_time:.1f}s"),
        ).model_dump(mode="json")

    def emergency_stop(**kwargs):
        backend.emergency_stop(True)
        return ToolResult(success=True, message=_dry("已急停")).model_dump(mode="json")

    def release_emergency_stop(**kwargs):
        backend.emergency_stop(False)
        return ToolResult(success=True, message=_dry("已解除急停")).model_dump(mode="json")

    return {
        "get_robot_status": get_robot_status,
        "move_robot_home": move_robot_home,
        "move_robot_xyz": move_robot_xyz,
        "move_path": move_path,
        "move_robot_joints": move_robot_joints,
        "emergency_stop": emergency_stop,
        "release_emergency_stop": release_emergency_stop,
    }
