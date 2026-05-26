"""SDK code generation tools — escape hatch: generate, approve, sandbox, execute."""

import inspect
import os
import resource
import re
import time
import subprocess
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
    r"ctypes\.",
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

# 注意：正则扫描是尽力而为的第一层防线，不是安全保证。
# 实际隔离由 RLIMIT_AS(512MB) + RLIMIT_NPROC(0) + python3 -I 保证。

# File write operations are ALLOWED (needed for writing scripts to /tmp).
# Protection is enforced by the clean_env whitelist and resource limits,
# not by blocking write APIs.


def _build_sandbox_header() -> str:
    """从 FakeEpisodeAPP 反射生成沙箱头部, 保证签名永不同步喵~"""
    from robocode.backends.sdk_backend import FakeEpisodeAPP

    fake = FakeEpisodeAPP()
    lines = [
        "# Auto-generated sandbox preamble (reflected from FakeEpisodeAPP)",
        "import sys, json, math, time",
        "",
        "class _SandboxEpisodeAPP:",
    ]

    _SAMPLE_ARGS: dict[str, list] = {
        "move_xyz_rotation": [[100, 0, 200], [180, 0, 90]],
        "move_linear_xyz_rotation": [[100, 0, 200], [180, 0, 90]],
        "angle_mode": [[180, 90, 83, 30, 110, 30]],
        "servo_gripper": [45],
        "emergency_stop": [False],
        "set_free_mode": [True],
    }

    for name in sorted(dir(fake)):
        if name.startswith("_"):
            continue
        method = getattr(fake, name)
        if not callable(method):
            continue

        sig = inspect.signature(method)
        params = []
        for p_name, p in sig.parameters.items():
            if p.default is inspect.Parameter.empty:
                params.append(p_name)
            else:
                params.append(f"{p_name}={p.default!r}")

        params_str = ", ".join(params)

        sample = _SAMPLE_ARGS.get(name)
        try:
            if sample:
                result = method(*sample)
            else:
                result = method()
        except Exception:
            result = 0.5

        lines.append(f"    def {name}(self, {params_str}):")
        lines.append(f"        return {result!r}")
        lines.append("")

    lines.append("robot = _SandboxEpisodeAPP()")
    return "\n".join(lines)


SANDBOX_HEADER = _build_sandbox_header()


class CodeSandbox:
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

        full_code = SANDBOX_HEADER + "\n" + code
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
                if k.startswith(("PYTHON", "PATH", "LANG", "LC_", "TMPDIR"))
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
