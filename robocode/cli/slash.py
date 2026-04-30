"""Slash command dispatcher — all commands handled locally, never sent to LLM."""

from dataclasses import dataclass


@dataclass
class SlashResult:
    message: str = ""
    handled: bool = False
    exit_requested: bool = False
    estop_requested: bool = False
    clear_screen: bool = False
    action: str = ""


class SlashDispatcher:
    def __init__(self):
        self._commands = {
            "/help": self._help,
            "/exit": self._exit,
            "/status": self._status,
            "/tools": self._tools,
            "/audit": self._audit,
            "/clear": self._clear,
            "/resume": self._resume,
            "/backend": self._backend,
            "/estop": self._estop,
        }

    def dispatch(self, user_input: str) -> SlashResult:
        stripped = user_input.strip()
        if not stripped.startswith("/"):
            return SlashResult()
        parts = stripped.split(maxsplit=1)
        cmd = parts[0]
        arg = parts[1] if len(parts) > 1 else ""
        handler = self._commands.get(cmd)
        if handler:
            return handler(arg)
        return SlashResult()

    def _help(self, _arg: str) -> SlashResult:
        return SlashResult(
            handled=True,
            message=(
                "可用命令：\n"
                "  /help        显示帮助\n"
                "  /exit        退出\n"
                "  /status      显示机器人和系统状态\n"
                "  /tools       列出所有工具\n"
                "  /audit       查看审计日志\n"
                "  /clear       清空对话上下文\n"
                "  /resume <id> 从检查点恢复会话\n"
                "  /backend     显示/切换后端\n"
                "  /estop       立即急停"
            ),
        )

    def _exit(self, _arg: str) -> SlashResult:
        return SlashResult(handled=True, exit_requested=True, message="再见~")

    def _status(self, _arg: str) -> SlashResult:
        return SlashResult(
            handled=True,
            message="后端: SDK (localhost:12345) | 状态: 未连接 | 急停: 否",
        )

    def _tools(self, _arg: str) -> SlashResult:
        return SlashResult(
            handled=True,
            message=(
                "L0: get_robot_status, check_calibration_status, detect_objects\n"
                "L1: move_robot_home, run_script\n"
                "L2: move_robot_xyz, move_robot_joints, control_suction, "
                "servo_gripper_control, simple_grasp, plan_grasp, "
                "generate_and_run_sdk_code"
            ),
        )

    def _audit(self, _arg: str) -> SlashResult:
        return SlashResult(handled=True, message="审计日志: 暂无记录（数据库未初始化）")

    def _clear(self, _arg: str) -> SlashResult:
        return SlashResult(handled=True, clear_screen=True, message="上下文已清空")

    def _resume(self, arg: str) -> SlashResult:
        return SlashResult(
            handled=True,
            message=f"尝试恢复会话 {arg}（checkpoint 功能尚未实现）",
        )

    def _backend(self, arg: str) -> SlashResult:
        if arg:
            return SlashResult(handled=True, message=f"后端已切换为: {arg}")
        return SlashResult(handled=True, message="当前后端: sdk (localhost:12345)")

    def _estop(self, _arg: str) -> SlashResult:
        return SlashResult(
            handled=True,
            estop_requested=True,
            message="急停已触发（本地命令，不经 LLM）",
        )
