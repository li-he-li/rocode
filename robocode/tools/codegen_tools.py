"""SDK code generation tools — escape hatch: generate, approve, sandbox, execute."""

import time
import subprocess
import re
from pathlib import Path
from robocode.utils.models import ToolResult

_ROBOCODE_DIR = Path(__file__).resolve().parent.parent  # robocode/
_GENERATED_DIR = _ROBOCODE_DIR / ".temp" / "generated"

FORBIDDEN_PATTERNS = [
    # Existing: socket, os, subprocess, eval/exec, ctypes, open write
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
    # 0.4.1: 12 new patterns for pathlib, io.open, compile, importlib, shutil
    r"\.write_text\(",  # pathlib.Path().write_text()
    r"\.write_bytes\(",  # pathlib.Path().write_bytes()
    r"io\.open\(",  # io.open()
    r"builtins\.open\(",  # builtins.open()
    r"compile\s*\(\s*[^,]+,\s*[^,]+,\s*['\"]exec",  # compile(..., 'exec')
    r"importlib\.import_module\(",  # dynamic import bypass
    r"shutil\.copy\(",  # shutil.copy()
    r"shutil\.move\(",  # shutil.move()
    r"shutil\.copytree\(",  # shutil.copytree()
    r"open\([^)]*['\"][wa][b+]?['\"]",  # open with write/append mode (w/wb/wa/a/ab)
    r"os\.chmod\(",  # os.chmod()
    r"os\.chown\(",  # os.chown()
]


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
    def run(cls, code: str, timeout_s: float = 30.0, save: bool = True) -> dict:
        violations = cls.scan_forbidden(code)
        if violations:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"禁止操作: {violations}",
                "timeout": False,
                "saved_path": "",
            }

        full_code = cls.SANDBOX_HEADER + "\n" + code
        saved_path = ""
        if save:
            _GENERATED_DIR.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%H%M%S")
            fname = f"gen_{ts}_{abs(hash(code)) % 10000:04d}.py"
            saved_path = str(_GENERATED_DIR / fname)
            try:
                with open(saved_path, "w", encoding="utf-8") as f:
                    f.write(code)
            except OSError:
                saved_path = ""

        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                ["python3", "-I", "-c", full_code],
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
            elapsed = (time.perf_counter() - t0) * 1000
            return {
                "success": proc.returncode == 0,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "timeout": False,
                "duration_ms": elapsed,
                "saved_path": saved_path,
            }
        except subprocess.TimeoutExpired:
            elapsed = (time.perf_counter() - t0) * 1000
            return {
                "success": False,
                "stdout": "",
                "stderr": "代码执行超时",
                "timeout": True,
                "duration_ms": elapsed,
                "saved_path": saved_path,
            }
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "timeout": False,
                "duration_ms": elapsed,
                "saved_path": saved_path,
            }


def make_codegen_tools(session_id: str = ""):
    def generate_and_run_sdk_code(*, code, summary="", **kwargs):
        result = CodeSandbox.run(code)
        # Runtime log
        from robocode.utils.runtime_log import log_codegen

        log_codegen(
            code=code,
            summary=summary,
            result=result,
            duration_ms=result.get("duration_ms", 0),
            session_id=session_id,
            saved_path=result.get("saved_path", ""),
        )
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
