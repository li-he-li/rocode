"""安全策略 — 风险门控、工作空间校验、审批检查喵~"""

from dataclasses import dataclass
from typing import Any
from robocode.config import Settings
from robocode.services.analytics.logger import get_logger

logger = get_logger("safety")


@dataclass
class SafetyCheck:
    """安全检查结果喵~"""

    passed: bool  # 是否通过
    reason: str = ""  # 未通过的原因
    details: dict[str, Any] = None  # 补充信息

    def __post_init__(self):
        if self.details is None:
            self.details = {}


class SafetyPolicy:
    """安全策略 — 关节限位、工作空间、速度、负载的硬性约束喵~"""

    # Episode 六轴机械臂关节限位 (min, max) 度
    JOINT_LIMITS = [
        (-180, 360),  # J1 底座旋转
        (-90, 270),  # J2 大臂俯仰
        (-180, 180),  # J3 小臂俯仰
        (-180, 180),  # J4 手腕旋转
        (-180, 180),  # J5 手腕俯仰
        (-180, 180),  # J6 末端自旋
    ]
    SUPPORTED_GRIPPERS = {"suction", "servo"}  # 支持的夹爪类型
    PROFILE_VERSION = "1.0.0"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()

    def check_joint_limits(self, angles: list[float]) -> SafetyCheck:
        """检查关节角度是否全部在限位范围内喵~"""
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
        """检查夹爪类型是否支持喵~"""
        return gripper_type in self.SUPPORTED_GRIPPERS

    def requires_approval(self, risk_level: str) -> bool:
        """根据风险级别判断是否需要审批喵~"""
        if risk_level == "L0":
            return False
        if risk_level == "L1":
            return False
        if risk_level == "L2":
            return self.settings.approval.l2_require_approval
        return True

    def check_workspace_bounds(self, x: float, y: float, z: float) -> SafetyCheck:
        """检查笛卡尔坐标是否在工作空间范围内喵~"""
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
        """检查速度比是否在安全范围内喵~"""
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
        """检查负载是否超限喵~"""
        if payload_g > self.settings.safety.max_payload_g:
            return SafetyCheck(
                passed=False,
                reason=f"负载 {payload_g}g 超过上限 {self.settings.safety.max_payload_g}g",
            )
        return SafetyCheck(passed=True)

    def _safe_float(self, key: str, params: dict) -> float | None:
        """安全地从参数中提取浮点数，类型错误返回 None 喵~"""
        val = params.get(key)
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def assert_not_estopped(self):
        """急停检查 — 如果急停已触发则抛出异常喵~"""
        if hasattr(self, "_backend") and self._backend:
            status = self._backend.get_status()
            if status.estop_active:
                raise RuntimeError("急停已触发，操作被拒绝")

    def check_workspace(self, x: float, y: float, z: float):
        """断言工作空间范围 — 违反抛 RuntimeError 喵~"""
        result = self.check_workspace_bounds(x, y, z)
        if not result.passed:
            raise RuntimeError(result.reason)

    def assert_joint_limits(self, angles: list[float]):
        """断言关节限位 — 违反抛 RuntimeError 喵~"""
        result = self.check_joint_limits(angles)
        if not result.passed:
            raise RuntimeError(result.reason)

    def check_operation(self, tool_name: str, params: dict) -> list[SafetyCheck]:
        """综合安全检查 — 根据工具名和参数执行对应的安全策略喵~"""
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
