"""机器人后端抽象接口 — 定义所有硬件操作的标准协议喵~"""

from abc import ABC, abstractmethod
from robocode.utils.models import RobotStatus, BackendHealth


class RobotBackend(ABC):
    """所有机器人后端的抽象基类喵~

    实现类需要提供: 状态查询、健康检查、运动控制、夹爪操作、急停等功能。
    """

    @abstractmethod
    def get_status(self) -> RobotStatus:
        """获取机器人当前状态（关节角度、位姿、急停状态）喵~"""
        ...

    @abstractmethod
    def health_check(self) -> BackendHealth:
        """检查后端连接健康状态喵~"""
        ...

    @abstractmethod
    def emergency_stop(self, enable: bool):
        """急停开关 — True=触发急停, False=解除喵~"""
        ...

    @abstractmethod
    def move_xyz_rotation(
        self,
        position: list[float],
        orientation: list[float],
        rotation_order: str = "zyx",
        speed_ratio: float = 1.0,
    ) -> float:
        """笛卡尔空间点到点运动（关节空间规划）喵~"""
        ...

    @abstractmethod
    def move_linear_xyz_rotation(
        self,
        position: list[float],
        orientation: list[float],
        rotation_order: str = "zyx",
        speed_ratio: float = 1.0,
    ) -> float:
        """笛卡尔空间直线运动（末端直线插补）喵~"""
        ...

    @abstractmethod
    def angle_mode(self, angles: list[float], speed_ratio: float = 1.0) -> float:
        """关节空间运动 — 直接指定 6 个关节角度喵~"""
        ...

    @abstractmethod
    def gripper_on(self):
        """吸盘开启喵~"""
        ...

    @abstractmethod
    def gripper_off(self):
        """吸盘关闭喵~"""
        ...

    @abstractmethod
    def servo_gripper(self, angle: int) -> float:
        """舵机夹爪角度控制 (0-110°) 喵~"""
        ...

    @abstractmethod
    def get_motor_angles(self) -> list[float] | None:
        """读取当前 6 关节角度，失败返回 None 喵~"""
        ...

    @abstractmethod
    def shutdown(self):
        """关闭后端连接，清理资源喵~"""
        ...
