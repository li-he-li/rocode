"""SDK code generation tools — escape hatch: generate, approve, sandbox, execute."""

import os
import resource
import time
import subprocess
import re
from pathlib import Path
from robocode.utils.models import ToolResult

_ROBOCODE_DIR = Path(__file__).resolve().parent.parent  # robocode/
_GENERATED_DIR = _ROBOCODE_DIR / ".temp" / "generated"

FORBIDDEN_PATTERNS = [
    r"import\s+socket",
    r"from\s+socket\s+import",
    r"os\.",
    r"os\s*,",
    r"import\s+os\b",
    r"from\s+os\b",
    r"subprocess\.",
    r"__import__\(",
    r"eval\(",
    r"exec\(",
    r"open\([^)]*['\"][wa]",
    r"open\([^)]*mode\s*=\s*['\"][wa]",
    r"ctypes\.",
    r"io\.open\(",
    r"builtins\.open\(",
    r"compile\s*\(\s*[^,]+,\s*[^,]+,\s*['\"]exec",
    r"importlib\b",
    r"shutil\.",
    r"__subclasses__",
    r"__builtins__",
    r"getattr\s*\(\s*__",
    r"globals\s*\(",
    r"locals\s*\(",
    r"vars\s*\(",
    r"dir\s*\(\s*__",
    r"\bgetattr\b.*\.__class__",
    r"type\s*\(\s*__",
]

# File write operations are ALLOWED (needed for writing scripts to /tmp).
# Protection is enforced by the clean_env whitelist and resource limits,
# not by blocking write APIs.


class CodeSandbox:
    # Parameter names MUST match real FakeEpisodeAPP — LLM uses keyword args per API docs
    SANDBOX_HEADER = """
# Auto-generated sandbox preamble
import sys, json, math, time

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
    def _sandbox_prelude(cls):
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))

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
            clean_env = {
                k: v
                for k, v in os.environ.items()
                if k.startswith(("PYTHON", "PATH", "HOME", "LANG", "LC_", "TMPDIR", "USER"))
            }
            proc = subprocess.run(
                ["python3", "-I", "-c", full_code],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                preexec_fn=cls._sandbox_prelude,
                env=clean_env,
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
