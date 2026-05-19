"""Safety policy — risk gates, workspace validation, approval checks."""

from dataclasses import dataclass
from typing import Any
from robocode.config import Settings
from robocode.services.analytics.logger import get_logger

logger = get_logger("safety")


@dataclass
class SafetyCheck:
    passed: bool
    reason: str = ""
    details: dict[str, Any] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


class SafetyPolicy:
    JOINT_LIMITS = [
        (-180, 360),  # joint1
        (-90, 270),  # joint2
        (-180, 180),  # joint3
        (-180, 180),  # joint4
        (-180, 180),  # joint5
        (-180, 180),  # joint6
    ]
    SUPPORTED_GRIPPERS = {"suction", "servo"}
    PROFILE_VERSION = "1.0.0"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()

    def check_joint_limits(self, angles: list[float]) -> SafetyCheck:
        if len(angles) != len(self.JOINT_LIMITS):
            return SafetyCheck(
                passed=False,
                reason=f"关节数应为 {len(self.JOINT_LIMITS)}，实际 {len(angles)}",
            )
        for i, angle in enumerate(angles):
            lo, hi = self.JOINT_LIMITS[i]
            if not (lo <= angle <= hi):
                return SafetyCheck(
                    passed=False,
                    reason=f"关节{i + 1}={angle} 超出范围 [{lo}, {hi}]",
                )
        return SafetyCheck(passed=True)

    def is_gripper_supported(self, gripper_type: str) -> bool:
        return gripper_type in self.SUPPORTED_GRIPPERS

    def requires_approval(self, risk_level: str) -> bool:
        if risk_level == "L0":
            return False
        if risk_level == "L1":
            return False
        if risk_level == "L2":
            return self.settings.approval.l2_require_approval
        return True

    def check_workspace_bounds(self, x: float, y: float, z: float) -> SafetyCheck:
        w = self.settings.workspace
        if not (w.x_min <= x <= w.x_max):
            return SafetyCheck(
                passed=False,
                reason=f"X={x} 超出工作空间 [{w.x_min}, {w.x_max}]mm",
            )
        if not (w.y_min <= y <= w.y_max):
            return SafetyCheck(
                passed=False,
                reason=f"Y={y} 超出工作空间 [{w.y_min}, {w.y_max}]mm",
            )
        if not (w.z_min <= z <= w.z_max):
            return SafetyCheck(
                passed=False,
                reason=f"Z={z} 超出工作空间 [{w.z_min}, {w.z_max}]mm",
            )
        return SafetyCheck(passed=True)

    def check_speed(self, speed_ratio: float) -> SafetyCheck:
        if speed_ratio <= 0:
            return SafetyCheck(
                passed=False,
                reason=f"速度比 {speed_ratio} 必须为正数",
            )
        if speed_ratio > self.settings.workspace.max_speed_ratio:
            return SafetyCheck(
                passed=False,
                reason=f"速度比 {speed_ratio} 超过上限 {self.settings.workspace.max_speed_ratio}",
            )
        return SafetyCheck(passed=True)

    def check_payload(self, payload_g: float) -> SafetyCheck:
        if payload_g > self.settings.safety.max_payload_g:
            return SafetyCheck(
                passed=False,
                reason=f"负载 {payload_g}g 超过上限 {self.settings.safety.max_payload_g}g",
            )
        return SafetyCheck(passed=True)

    def _safe_float(self, key: str, params: dict) -> float | None:
        val = params.get(key)
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def check_operation(self, tool_name: str, params: dict) -> list[SafetyCheck]:
        logger.info("safety_check", tool_name=tool_name)
        results = []
        x = self._safe_float("x", params)
        y = self._safe_float("y", params)
        z = self._safe_float("z", params)
        if x is not None and y is not None and z is not None:
            results.append(self.check_workspace_bounds(x, y, z))
        elif any(k in params for k in ("x", "y", "z")):
            results.append(SafetyCheck(passed=False, reason="坐标参数必须为数字"))
        speed = self._safe_float("speed_ratio", params)
        if speed is not None:
            results.append(self.check_speed(speed))
        elif "speed_ratio" in params:
            results.append(SafetyCheck(passed=False, reason="速度比必须为数字"))
        payload = self._safe_float("payload_g", params)
        if payload is not None:
            results.append(self.check_payload(payload))
        elif "payload_g" in params:
            results.append(SafetyCheck(passed=False, reason="负载参数必须为数字"))
        return results or [SafetyCheck(passed=True)]
