"""Robot backend abstract interface."""

from abc import ABC, abstractmethod
from robocode.utils.models import RobotStatus, BackendHealth


class RobotBackend(ABC):
    @abstractmethod
    def get_status(self) -> RobotStatus: ...

    @abstractmethod
    def health_check(self) -> BackendHealth: ...

    @abstractmethod
    def emergency_stop(self, enable: bool): ...

    @abstractmethod
    def move_xyz_rotation(
        self,
        position: list[float],
        orientation: list[float],
        rotation_order: str = "zyx",
        speed_ratio: float = 1.0,
    ) -> float: ...

    @abstractmethod
    def move_linear_xyz_rotation(
        self,
        position: list[float],
        orientation: list[float],
        rotation_order: str = "zyx",
        speed_ratio: float = 1.0,
    ) -> float: ...

    @abstractmethod
    def angle_mode(self, angles: list[float], speed_ratio: float = 1.0) -> float: ...

    @abstractmethod
    def gripper_on(self): ...

    @abstractmethod
    def gripper_off(self): ...

    @abstractmethod
    def servo_gripper(self, angle: int) -> float: ...

    @abstractmethod
    def get_motor_angles(self) -> list[float] | None: ...

    @abstractmethod
    def shutdown(self): ...
