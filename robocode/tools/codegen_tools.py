"""SDK code generation tools — escape hatch: generate, approve, sandbox, execute."""

import subprocess
import re
from dataclasses import dataclass
from robocode.utils.models import ToolResult


FORBIDDEN_PATTERNS = [
    r"import\s+socket",
    r"from\s+socket\s+import",
    r"os\.remove\(",
    r"os\.unlink\(",
    r"os\.rmdir\(",
    r"os\.system\(",
    r"os\.popen\(",
    r"shutil\.rmtree\(",
    r"subprocess\.",
    r"__import__\(",
    r"eval\(",
    r"exec\(",
    r"open\([^)]*['\"][wa]",
    r"open\([^)]*mode\s*=\s*['\"][wa]",
    r"ctypes\.",
]


@dataclass
class CodeApprovalRequest:
    tool_name: str
    code: str
    summary: str
    requires_approval: bool = True

    def format_prompt(self) -> str:
        return (
            "[approval needed] SDK 代码待确认\n\n"
            f"  摘要: {self.summary}\n"
            "  代码:\n"
            f"{self.code}\n\n"
            "  [Y] 批准   [N] 拒绝"
        )


class CodeSandbox:
    # Parameter names MUST match real FakeEpisodeAPP — LLM uses keyword args per API docs
    SANDBOX_HEADER = """
# Auto-generated sandbox preamble
import sys, os, json, math, time

class _SandboxEpisodeAPP:
    def move_xyz_rotation(self, position, orientation, rotation_order="zyx", speed_ratio=1.0):
        return 0.5
    def angle_mode(self, angles, speed_ratio=1.0):
        return 0.5
    def get_motor_angles(self):
        return [180.0, 90.0, 83.0, 30.0, 110.0, 30.0]
    def get_pose(self, rotation_order="xyz"):
        return [260.0, 0.0, 200.0, 180.0, 0.0, 90.0]
    def gripper_on(self):
        return 0.05
    def gripper_off(self):
        return 0.05
    def servo_gripper(self, angle):
        return 1.0
    def emergency_stop(self, enable):
        return 0.05

robot = _SandboxEpisodeAPP()
"""

    @classmethod
    def scan_forbidden(cls, code: str) -> list[str]:
        return [p for p in FORBIDDEN_PATTERNS if re.search(p, code)]

    @classmethod
    def run(cls, code: str, timeout_s: float = 30.0) -> dict:
        violations = cls.scan_forbidden(code)
        if violations:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"禁止操作: {violations}",
                "timeout": False,
            }

        full_code = cls.SANDBOX_HEADER + "\n" + code
        try:
            proc = subprocess.run(
                ["python3", "-c", full_code],
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
            return {
                "success": proc.returncode == 0,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "timeout": False,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "stdout": "",
                "stderr": "代码执行超时",
                "timeout": True,
            }
        except Exception as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "timeout": False,
            }


def make_codegen_tools():
    def generate_and_run_sdk_code(*, code, summary="", **kwargs):
        result = CodeSandbox.run(code)
        if result["success"]:
            return ToolResult(
                success=True, message=f"代码执行成功: {summary}", metrics=result
            ).model_dump(mode="json")
        return ToolResult(
            success=False,
            message=f"代码执行失败: {result.get('stderr', '')}",
            metrics=result,
        ).model_dump(mode="json")

    return {
        "generate_and_run_sdk_code": generate_and_run_sdk_code,
    }
