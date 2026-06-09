"""系统共享数据模型 — ToolResult, RobotStatus, BackendHealth 喵~"""

from typing import Any
from pydantic import BaseModel


class ToolResult(BaseModel):
    """工具执行结果 — 统一的成功/失败返回格式喵~"""

    success: bool  # 是否成功
    message: str = ""  # 人类可读的结果描述
    metrics: dict[str, Any] = {}  # 指标数据（角度、耗时等）
    artifacts: dict[str, str] = {}  # 产物（生成的代码等）


class RobotStatus(BaseModel):
    """机械臂完整状态快照喵~"""

    connected: bool  # 是否连接到后端
    motor_angles: list[float] = []  # 6 关节角度 (度)
    pose: list[float] = []  # 末端位姿 [x, y, z, rx, ry, rz]
    estop_active: bool = False  # 急停是否触发
    free_mode: bool = False  # 是否自由模式
    backend: str = ""  # 后端类型标识

    def to_rich(self) -> str:
        """生成 Rich 格式的 CLI 状态显示字符串喵~"""
        if not self.connected:
            return f"[red]离线[/red] ({self.backend})"
        angles = ", ".join(f"{a:.1f}°" for a in self.motor_angles) if self.motor_angles else "N/A"
        pose = ", ".join(f"{v:.1f}" for v in self.pose) if self.pose else "N/A"
        estop = "[red]急停中[/red]" if self.estop_active else "[green]正常[/green]"
        return (
            f"[green]在线[/green] ({self.backend})\n"
            f"  关节: {angles}\n"
            f"  位姿: {pose}\n"
            f"  状态: {estop}"
        )


class BackendHealth(BaseModel):
    """后端健康检查结果喵~"""

    healthy: bool  # 后端是否健康
    backend: str  # 后端类型
    latency_ms: float = 0.0  # 响应延迟 (ms)
    message: str = ""  # 附加信息
