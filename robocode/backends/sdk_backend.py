"""SDK 后端 — EpisodeAPP TCP 适配器，支持真机/Fake 双模式 + 变体选择喵~"""

from enum import Enum
from robocode.backends.base import RobotBackend
from robocode.utils.models import RobotStatus, BackendHealth
from robocode.services.analytics.logger import get_logger

logger = get_logger("backend")


class EpisodeVariant(str, Enum):
    """Episode 机械臂变体喵~"""

    SDK = "sdk"  # 基础 SDK 模式
    D3 = "3d"  # 3D 视觉模式
    D6 = "6d"  # 6D 抓取模式


class FakeEpisodeAPP:
    """无硬件测试用的假 EpisodeAPP 喵~

    所有运动方法返回模拟耗时（含随机延迟），关节角度保存在内存中。
    """

    def __init__(self):
        self._angles = [180.0, 90.0, 83.0, 30.0, 110.0, 30.0]  # Home 位姿
        self._estop = False
        self._connected = True

    def get_motor_angles(self):
        return list(self._angles)

    def get_pose(self, rotation_order="xyz"):
        return [260.0, 0.0, 200.0, 180.0, 0.0, 90.0]

    def emergency_stop(self, enable):
        self._estop = bool(enable)
        return 0.05

    def move_xyz_rotation(self, position, orientation, rotation_order="zyx", speed_ratio=1.0):
        import random
        import time as _t

        _t.sleep(random.uniform(0.1, 0.5))  # 模拟真实运动延迟喵~
        return round(random.uniform(0.5, 2.0), 1)

    def move_linear_xyz_rotation(
        self, position, orientation, rotation_order="zyx", speed_ratio=1.0
    ):
        import random
        import time as _t

        _t.sleep(random.uniform(0.1, 0.5))
        return round(random.uniform(0.5, 2.0), 1)

    def angle_mode(self, angles, speed_ratio=1.0):
        import random
        import time as _t

        _t.sleep(random.uniform(0.1, 0.5))  # 模拟真实关节运动延迟喵~
        self._angles = list(angles)
        return round(random.uniform(0.5, 2.0), 1)

    def gripper_on(self):
        return 0.05

    def gripper_off(self):
        return 0.05

    def servo_gripper(self, angle):
        import random
        import time as _t

        _t.sleep(random.uniform(0.05, 0.2))
        return round(random.uniform(0.5, 1.5), 1)

    def set_free_mode(self, mode):
        return 0.1


class SdkBackend(RobotBackend):
    """SDK 后端实现 — 封装 EpisodeAPP TCP 客户端喵~

    client 可以是真实 EpisodeAPP 或 FakeEpisodeAPP（测试/离线模式）。
    """

    def __init__(self, client=None, variant: EpisodeVariant = EpisodeVariant.SDK):
        self._client = client or FakeEpisodeAPP()
        self.variant = variant
        self.active_backend = "sdk"
        self._connected = True

    @property
    def is_fake(self) -> bool:
        """是否使用 Fake 客户端喵~"""
        return isinstance(self._client, FakeEpisodeAPP)

    def get_status(self) -> RobotStatus:
        """获取完整机器人状态喵~"""
        if not self._connected:
            return RobotStatus(connected=False, backend=self.active_backend)
        try:
            angles = self._client.get_motor_angles()
            pose = self._client.get_pose()
            if angles is None:
                return RobotStatus(connected=False, backend=self.active_backend)
            return RobotStatus(
                connected=True,
                motor_angles=list(angles),
                pose=list(pose) if pose is not None else [],
                estop_active=getattr(self._client, "_estop", False),
                backend=f"sdk/{self.variant.value}",
            )
        except Exception:
            return RobotStatus(connected=False, backend=self.active_backend)

    def health_check(self) -> BackendHealth:
        """后端健康检查 — 测量 get_motor_angles 的延迟喵~"""
        import time

        t0 = time.perf_counter()
        try:
            angles = self._client.get_motor_angles()
            latency = (time.perf_counter() - t0) * 1000
            return BackendHealth(
                healthy=angles is not None and len(angles) == 6,
                backend=self.active_backend,
                latency_ms=round(latency, 2),
            )
        except Exception:
            return BackendHealth(healthy=False, backend=self.active_backend)

    def emergency_stop(self, enable: bool):
        """急停/解除急停喵~"""
        self._client.emergency_stop(1 if enable else 0)

    def move_xyz_rotation(
        self,
        position: list[float],
        orientation: list[float],
        rotation_order: str = "zyx",
        speed_ratio: float = 1.0,
    ) -> float:
        return self._client.move_xyz_rotation(position, orientation, rotation_order, speed_ratio)

    def move_linear_xyz_rotation(
        self,
        position: list[float],
        orientation: list[float],
        rotation_order: str = "zyx",
        speed_ratio: float = 1.0,
    ) -> float:
        return self._client.move_linear_xyz_rotation(
            position, orientation, rotation_order, speed_ratio
        )

    def angle_mode(self, angles: list[float], speed_ratio: float = 1.0) -> float:
        return self._client.angle_mode(angles, speed_ratio)

    def gripper_on(self):
        self._client.gripper_on()

    def gripper_off(self):
        self._client.gripper_off()

    def servo_gripper(self, angle: int) -> float:
        return self._client.servo_gripper(angle)

    def get_motor_angles(self) -> list[float] | None:
        """安全读取关节角度，异常返回 None 喵~"""
        try:
            angles = self._client.get_motor_angles()
            return list(angles) if angles is not None else None
        except Exception:
            return None

    def shutdown(self):
        """关闭后端连接喵~"""
        self._connected = False
