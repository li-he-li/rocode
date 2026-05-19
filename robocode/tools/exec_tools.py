"""Controlled host execution — operator-approved subprocess with audit."""

import re
import shlex
import subprocess
from robocode.utils.models import ToolResult

FORBIDDEN_PATTERNS = [
    re.compile(p)
    for p in [
        r"rm\s+-rf\s+/",
        r"mkfs\.",
        r"dd\s+(if|of)=",
        r":\(\)\{\s*:\|:&\s*\};:",
        r"\b(shutdown|reboot|halt|poweroff)\b",
        r"\b(wget|curl)\b",
        r"\bpip\s+install\b",
        r"\bapt(-get)?\s+install\b",
        r"\byum\s+install\b",
    ]
]

SHELL_META_PATTERN = re.compile(r"[|;`$>&<\n\r]")


def _is_safe(command: str) -> tuple[bool, str]:
    if SHELL_META_PATTERN.search(command):
        return False, "命令包含 shell 元字符 (| ; ` $ > & <)，仅允许单命令"
    for pattern in FORBIDDEN_PATTERNS:
        match = pattern.search(command)
        if match:
            return False, f"命令包含禁止操作: {match.group()}"
    return True, ""


def execute_command(*, command: str, timeout_s: float = 30.0, cwd: str = "", **kwargs) -> dict:
    safe, reason = _is_safe(command)
    if not safe:
        return ToolResult(success=False, message=reason).model_dump(mode="json")

    try:
        args = shlex.split(command)
    except ValueError as e:
        return ToolResult(success=False, message=f"命令解析失败: {e}").model_dump(mode="json")

    try:
        proc = subprocess.run(
            args,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=cwd or None,
        )
        return ToolResult(
            success=proc.returncode == 0,
            message="执行完成" if proc.returncode == 0 else f"退出码: {proc.returncode}",
            metrics={
                "stdout": proc.stdout[-5000:],
                "stderr": proc.stderr[-2000:],
                "returncode": proc.returncode,
            },
        ).model_dump(mode="json")
    except FileNotFoundError:
        return ToolResult(success=False, message=f"命令未找到: {args[0]}").model_dump(mode="json")
    except subprocess.TimeoutExpired:
        return ToolResult(success=False, message=f"命令超时 ({timeout_s}s)").model_dump(mode="json")
    except Exception as e:
        return ToolResult(success=False, message=str(e)).model_dump(mode="json")


def make_exec_tools() -> dict:
    return {"execute_command": execute_command}
