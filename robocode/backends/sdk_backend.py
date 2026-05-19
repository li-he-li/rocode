"""SDK backend — EpisodeAPP TCP socket adapter with variant selection."""

from enum import Enum
from robocode.backends.base import RobotBackend
from robocode.utils.models import RobotStatus, BackendHealth
from robocode.services.analytics.logger import get_logger

logger = get_logger("backend")


class EpisodeVariant(str, Enum):
    SDK = "sdk"
    D3 = "3d"
    D6 = "6d"


class FakeEpisodeAPP:
    """Fake EpisodeAPP for testing without hardware."""

    def __init__(self):
        self._angles = [180.0, 90.0, 83.0, 30.0, 110.0, 30.0]
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
        return 0.5

    def move_linear_xyz_rotation(
        self, position, orientation, rotation_order="zyx", speed_ratio=1.0
    ):
        return 0.5

    def angle_mode(self, angles, speed_ratio=1.0):
        self._angles = list(angles)
        return 0.5

    def gripper_on(self):
        return 0.05

    def gripper_off(self):
        return 0.05

    def servo_gripper(self, angle):
        return 1.0

    def set_free_mode(self, mode):
        return 0.1


class SdkBackend(RobotBackend):
    def __init__(self, client=None, variant: EpisodeVariant = EpisodeVariant.SDK):
        self._client = client or FakeEpisodeAPP()
        self.variant = variant
        self.active_backend = "sdk"
        self._connected = True

    @property
    def is_fake(self) -> bool:
        return isinstance(self._client, FakeEpisodeAPP)

    def get_status(self) -> RobotStatus:
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
        try:
            angles = self._client.get_motor_angles()
            return list(angles) if angles is not None else None
        except Exception:
            return None

    def shutdown(self):
        self._connected = False
