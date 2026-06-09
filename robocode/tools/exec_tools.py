"""受控主机命令执行 — 操作者审批 + 安全模式检查喵~"""

import re
import shlex
import subprocess
from robocode.utils.models import ToolResult

# 危险命令禁止模式 — 硬性拦截，不会进入审批流程
FORBIDDEN_PATTERNS = [
    re.compile(p)
    for p in [
        r"rm\s+-rf\s+/",  # 递归删除根目录
        r"mkfs\.",  # 格式化文件系统
        r"dd\s+(if|of)=",  # 磁盘直接读写
        r":\(\)\{\s*:\|:&\s*\};:",  # Fork 炸弹
        r"\b(shutdown|reboot|halt|poweroff)\b",  # 关机/重启
        r"\b(wget|curl)\b",  # 网络下载
        r"\bpip\s+install\b",  # pip 安装
        r"\bapt(-get)?\s+install\b",  # apt 安装
        r"\byum\s+install\b",  # yum 安装
    ]
]

# Shell 元字符 — 拒绝管道/重定向/链式命令，只允许单命令
SHELL_META_PATTERN = re.compile(r"[|;`$>&<\n\r]")


def _is_safe(command: str) -> tuple[bool, str]:
    """检查命令是否安全 — 无 shell 元字符 + 无禁止模式喵~"""
    if SHELL_META_PATTERN.search(command):
        return False, "命令包含 shell 元字符 (| ; ` $ > & <)，仅允许单命令"
    for pattern in FORBIDDEN_PATTERNS:
        match = pattern.search(command)
        if match:
            return False, f"命令包含禁止操作: {match.group()}"
    return True, ""


def execute_command(*, command: str, timeout_s: float = 30.0, cwd: str = "", **kwargs) -> dict:
    """在主机上安全执行单条命令喵~

    限制: 无管道/重定向/链式, 禁止危险操作, shell=False 执行。
    """
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
            shell=False,  # 关键安全措施: 不经过 shell
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
    """返回 execute_command handler 喵~"""
    return {"execute_command": execute_command}
