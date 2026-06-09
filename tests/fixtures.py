"""Fake 后端 fixtures — 无硬件确定性测试喵~"""

from robocode.utils.models import RobotStatus, BackendHealth


class FakeRobotBackend:
    """返回可配置响应的 Fake 后端，不连接真实硬件喵~"""

    def __init__(self):
        self._motor_angles = [180.0, 90.0, 83.0, 30.0, 110.0, 30.0]  # Home 位姿
        self._pose = [260.0, 0.0, 200.0, 180.0, 0.0, 90.0]
        self._estop = False
        self._free_mode = False
        self._connected = True

    def set_motor_angles(self, angles: list[float]):
        """设置关节角度（测试中用于预设状态）喵~"""
        self._motor_angles = list(angles)

    def get_status(self) -> RobotStatus:
        """返回当前 Fake 状态喵~"""
        return RobotStatus(
            connected=self._connected,
            motor_angles=list(self._motor_angles),
            pose=list(self._pose),
            estop_active=self._estop,
            free_mode=self._free_mode,
            backend="fake",
        )

    def health_check(self) -> BackendHealth:
        """Fake 后端始终健康喵~"""
        return BackendHealth(healthy=self._connected, backend="fake", latency_ms=1.0)

    def emergency_stop(self, enable: bool):
        self._estop = bool(enable)

    def move_xyz_rotation(self, position, orientation, rotation_order="zyx", speed_ratio=1.0):
        """模拟运动 — 更新内部位姿喵~"""
        self._pose = list(position) + list(orientation)
        return 0.5

    def angle_mode(self, angles, speed_ratio=1.0):
        """模拟关节运动 — 更新内部角度喵~"""
        self._motor_angles = list(angles)
        return 0.5

    def gripper_on(self):
        return 0.05

    def gripper_off(self):
        return 0.05

    def servo_gripper(self, angle):
        return 1.0

    def get_motor_angles(self):
        """返回当前关节角度副本喵~"""
        return list(self._motor_angles)

    def move_linear_xyz_rotation(
        self, position, orientation, rotation_order="zyx", speed_ratio=1.0
    ):
        """模拟直线运动喵~"""
        self._pose = list(position) + list(orientation)
        return 0.5

    def shutdown(self):
        """模拟关闭连接喵~"""
        self._connected = False
