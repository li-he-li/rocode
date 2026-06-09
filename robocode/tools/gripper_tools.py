"""夹爪工具 — 吸盘 + 舵机夹爪控制 + 兼容性检查喵~"""

from robocode.backends.base import RobotBackend
from robocode.orchestrator.safety import SafetyPolicy
from robocode.utils.models import ToolResult


def make_gripper_tools(backend: RobotBackend, safety: SafetyPolicy) -> dict:
    """构建夹爪控制工具 handler 映射喵~"""
    _is_fake = getattr(backend, "is_fake", False)

    def _dry(msg: str) -> str:
        """Fake 模式前缀标记喵~"""
        return f"[模拟模式-非真实硬件] {msg}" if _is_fake else msg

    def control_suction(*, action, **kwargs):
        """吸盘夹爪开/关 — action 为 "on" 或 "off" 喵~"""
        if action not in ("on", "off"):
            return ToolResult(success=False, message=f"无效动作: {action}，应为 on/off").model_dump(
                mode="json"
            )
        if not safety.is_gripper_supported("suction"):
            return ToolResult(success=False, message="吸盘夹爪不可用").model_dump(mode="json")
        if action == "on":
            backend.gripper_on()
        else:
            backend.gripper_off()
        return ToolResult(success=True, message=_dry(f"吸盘已{action}")).model_dump(mode="json")

    def servo_gripper_control(*, angle, **kwargs):
        """舵机夹爪角度控制 — 0=全开, 110=全闭喵~"""
        angle = int(angle)
        if not (0 <= angle <= 110):
            return ToolResult(
                success=False, message=f"舵机角度 {angle} 超出范围 [0,110]"
            ).model_dump(mode="json")
        if not safety.is_gripper_supported("servo"):
            return ToolResult(success=False, message="舵机夹爪不可用").model_dump(mode="json")
        backend.servo_gripper(angle)
        return ToolResult(success=True, message=_dry(f"舵机角度已设为 {angle}")).model_dump(
            mode="json"
        )

    return {
        "control_suction": control_suction,
        "servo_gripper_control": servo_gripper_control,
    }
