"""Controlled host execution — operator-approved subprocess with audit."""

import subprocess
from robocode.utils.models import ToolResult


FORBIDDEN_CMDS = [
    "rm -rf /",
    "mkfs.",
    "dd if=",
    "dd of=",
    ":(){ :|:& };:",  # fork bomb
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "chmod 777 /",
    "chmod +x",
    "chown -r",
    "wget ",
    "curl ",
    "| tee ",
    "tee /",
]


def _normalize_whitespace(s: str) -> str:
    import re

    return re.sub(r"\s+", " ", s).strip()


def _is_safe(command: str) -> tuple[bool, str]:
    normalized = _normalize_whitespace(command.lower())
    for bad in FORBIDDEN_CMDS:
        bad_normalized = _normalize_whitespace(bad)
        if bad_normalized in normalized:
            return False, f"命令包含禁止操作: {bad}"
    return True, ""


def execute_command(*, command: str, timeout_s: float = 30.0, cwd: str = "", **kwargs) -> dict:
    safe, reason = _is_safe(command)
    if not safe:
        return ToolResult(success=False, message=reason).model_dump(mode="json")

    try:
        proc = subprocess.run(
            command,
            shell=True,
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
    except subprocess.TimeoutExpired:
        return ToolResult(success=False, message=f"命令超时 ({timeout_s}s)").model_dump(mode="json")
    except Exception as e:
        return ToolResult(success=False, message=str(e)).model_dump(mode="json")


def make_exec_tools() -> dict:
    return {"execute_command": execute_command}
