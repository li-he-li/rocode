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


class BackendHealth(BaseModel):
    healthy: bool
    backend: str
    latency_ms: float = 0.0
    message: str = ""
