"""Shared result and metadata models used across the system."""

from typing import Any
from pydantic import BaseModel


class ToolResult(BaseModel):
    success: bool
    message: str = ""
    metrics: dict[str, Any] = {}
    artifacts: dict[str, str] = {}


class RobotStatus(BaseModel):
    connected: bool
    motor_angles: list[float] = []
    pose: list[float] = []  # [x, y, z, rx, ry, rz]
    estop_active: bool = False
    free_mode: bool = False
    backend: str = ""

    def to_rich(self) -> str:
        """Rich-formatted status string for CLI display."""
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
    healthy: bool
    backend: str
    latency_ms: float = 0.0
    message: str = ""
