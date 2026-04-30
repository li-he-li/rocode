"""Shared result, error, and metadata models used across the system."""

from typing import Any
from enum import Enum
from pydantic import BaseModel


class RiskLevel(str, Enum):
    L0 = "L0"  # Read-only queries, auto-approved
    L1 = "L1"  # Minor motion/config, logged
    L2 = "L2"  # Real motion/grasp/file-write, requires approval


class SafetyFlag(str, Enum):
    NEAR_WORKSPACE_BOUNDARY = "near_workspace_boundary"
    LOW_CONFIDENCE_DETECTION = "low_confidence_detection"
    IK_FAILED = "ik_failed"
    TIMEOUT = "timeout"
    CALIBRATION_DEGRADED = "calibration_degraded"


class ToolResult(BaseModel):
    success: bool
    message: str = ""
    metrics: dict[str, Any] = {}
    artifacts: dict[str, str] = {}
    safety_flags: list[SafetyFlag] = []


class ToolError(BaseModel):
    tool_name: str
    error_class: str
    message: str
    evidence: dict[str, Any] = {}
    remediation: str = ""


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


class ApprovalRequest(BaseModel):
    tool_name: str
    risk_level: RiskLevel
    params: dict[str, Any]
    summary: str
    details: dict[str, Any] = {}


class Artifact(BaseModel):
    name: str
    path: str
    kind: str  # "yaml", "image", "log", "trajectory"
    tool_call_id: str = ""
    session_id: str = ""
