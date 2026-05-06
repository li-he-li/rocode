"""CLI main entry — prompt_toolkit REPL integrated with AgentLoop + DeepSeek."""

import asyncio
import json
import os
import signal
import sys
import termios
import tty

from rich.console import Console
from rich.panel import Panel
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.key_binding import KeyBindings

from robocode.cli.slash import SlashDispatcher
from robocode.cli.skill_loader import load_skills
from robocode.agent.core import AgentLoop
from robocode.llm.deepseek_provider import DeepSeekProvider
from robocode.config import Settings
from robocode.tools.registry import ToolEntry, SkillEntry, ToolRegistry
from robocode.tools.script_tools import SCRIPT_INVENTORY
from robocode.tools.motion_tools import make_motion_tools
from robocode.tools.gripper_tools import make_gripper_tools
from robocode.tools.script_tools import make_script_tools
from robocode.tools.codegen_tools import make_codegen_tools
from robocode.tools.exec_tools import make_exec_tools
from robocode.tools.code_tools import make_code_tools
from robocode.tools.patch_tools import make_patch_tools
from robocode.tools.wrapper_tools import make_wrapper_tools
from robocode.backends.sdk_backend import SdkBackend
from robocode.orchestrator.safety import SafetyPolicy
from robocode.utils.cleanup import run_startup_cleanup
from robocode.orchestrator.approval import ApprovalGate
from robocode.orchestrator.tool_guard import ToolGuard
from robocode.persistence.db import AuditDB

PROMPT_STYLE = Style.from_dict({"prompt": "#00ff00 bold"})


class RobocodeApp:
    def __init__(self, fake: bool = False):
        self.console = Console()
        self._explicit_fake = fake
        kb = KeyBindings()

        @kb.add("escape")
        def _(event):
            if self._agent_task and not self._agent_task.done():
                self._agent_task.cancel()
                self.console.print("\n[yellow]⏹ 已中断[/yellow]")

        self.session = PromptSession(history=InMemoryHistory(), key_bindings=kb)
        self._running = True
        self._agent_task = None
        self._agent_running = False

        self.settings = Settings()
        run_startup_cleanup()
        self.db = AuditDB()
        self.db.initialize()
        self._session_id = self.db.create_session(backend=self.settings.active_backend)
        self.slash = SlashDispatcher(db=self.db)

        self.safety = SafetyPolicy(self.settings)
        self.approval = ApprovalGate()

        # Backend
        self._backend_fake = False
        if self._explicit_fake:
            self._backend_fake = True
            from robocode.backends.sdk_backend import FakeEpisodeAPP

            self.backend = SdkBackend(client=FakeEpisodeAPP())
        else:
            try:
                # Ensure project root is on path (needed when running from robocode/ subdir)
                _project = os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                )
                if _project not in sys.path:
                    sys.path.insert(0, _project)
                from src.SDK.sdk_demo import EpisodeAPP

                ep = EpisodeAPP(
                    ip=self.settings.backend.sdk_host,
                    port=self.settings.backend.sdk_port,
                )
                # Quick connectivity test
                try:
                    angles = ep.get_motor_angles()
                    if angles is None or len(angles) != 6:
                        raise ConnectionError("SDK 返回异常数据")
                except Exception as conn_err:
                    raise ConnectionError(f"SDK 连接测试失败: {conn_err}")
                self.backend = SdkBackend(client=ep)
            except Exception as e:
                self._backend_fake = True
                from robocode.backends.sdk_backend import FakeEpisodeAPP

                self.backend = SdkBackend(client=FakeEpisodeAPP())
                self._backend_error = str(e)

        # Tool registry
        self.registry = ToolRegistry()
        self._register_tools()

        # Build risk_levels lookup from registry
        risk_levels = {}
        for entry in self.registry._entries.values():
            risk_levels[entry.name] = entry.risk_level

        # ToolGuard wiring
        self.tool_guard = ToolGuard(
            approval_gate=self.approval,
            audit_db=self.db,
            safety_policy=self.safety,
            approval_settings=self.settings.approval,
            owner_callback=self._owner_approval_callback,
            session_id=self._session_id,
        )

        # Agent
        self.agent = AgentLoop(
            provider=DeepSeekProvider(self.settings),
            tool_handlers=self._build_handler_map(),
            tool_schemas=self.registry.all_schemas(),
            guard=self.tool_guard,
            risk_levels=risk_levels,
            db=self.db,
            session_id=self._session_id,
        )

        # Wire registry + backend into slash dispatcher (created before them)
        self.slash._registry = self.registry
        self.slash._robot_backend = self.backend

    def _register_tools(self):
        entries = [
            ToolEntry(
                name="get_robot_status",
                description="获取机械臂当前状态：关节角度、末端位姿、急停状态",
                parameters={"type": "object", "properties": {}},
                risk_level="L0",
            ),
            ToolEntry(
                name="move_robot_home",
                description="机械臂回到安全零位 [260, 0, 200]",
                parameters={"type": "object", "properties": {}},
                risk_level="L1",
            ),
            ToolEntry(
                name="move_robot_xyz",
                description="移动机械臂末端到指定笛卡尔坐标 (mm)",
                parameters={
                    "type": "object",
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "z": {"type": "number"},
                        "speed_ratio": {"type": "number"},
                    },
                    "required": ["x", "y", "z"],
                },
                risk_level="L2",
            ),
            ToolEntry(
                name="move_robot_joints",
                description="移动机械臂各关节到指定角度 (度)",
                parameters={
                    "type": "object",
                    "properties": {"angles": {"type": "array"}, "speed_ratio": {"type": "number"}},
                    "required": ["angles"],
                },
                risk_level="L2",
            ),
            ToolEntry(
                name="emergency_stop",
                description="立即急停（仅 enable=true）。解除急停请用 release_emergency_stop",
                parameters={"type": "object", "properties": {}},
                risk_level="L0",
            ),
            ToolEntry(
                name="release_emergency_stop",
                description="解除急停，恢复机械臂运动能力",
                parameters={"type": "object", "properties": {}},
                risk_level="L2",
            ),
            ToolEntry(
                name="control_suction",
                description="吸盘夹爪开/关",
                parameters={
                    "type": "object",
                    "properties": {"action": {"type": "string", "enum": ["on", "off"]}},
                    "required": ["action"],
                },
                risk_level="L2",
            ),
            ToolEntry(
                name="servo_gripper_control",
                description="舵机夹爪角度控制 (0-110)",
                parameters={
                    "type": "object",
                    "properties": {"angle": {"type": "integer"}},
                    "required": ["angle"],
                },
                risk_level="L2",
            ),
            ToolEntry(
                name="check_calibration_status",
                description="读取标定文件状态",
                parameters={"type": "object", "properties": {"calib_type": {"type": "string"}}},
                risk_level="L0",
            ),
            ToolEntry(
                name="run_script",
                description="启动标定/检测等脚本（需操作者确认）",
                parameters={
                    "type": "object",
                    "properties": {"script_name": {"type": "string"}},
                    "required": ["script_name"],
                },
                risk_level="L1",
            ),
            ToolEntry(
                name="generate_and_run_sdk_code",
                description="【逃生舱】生成并执行 SDK 代码实现自定义动作",
                parameters={
                    "type": "object",
                    "properties": {"code": {"type": "string"}, "summary": {"type": "string"}},
                    "required": ["code"],
                },
                risk_level="L2",
            ),
            ToolEntry(
                name="list_skills",
                description="列出所有可用技能（标定/检测/抓取/应用脚本），包括名称、类别、是否需要人工操作",
                parameters={"type": "object", "properties": {}},
                risk_level="L0",
            ),
            ToolEntry(
                name="execute_command",
                description="【L2 需审批】在主机上执行命令。危险命令(rm -rf /, shutdown等)硬拦截。优先使用 read_file/search_code/run_script 替代。",
                parameters={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "要执行的命令"},
                        "timeout_s": {"type": "number", "description": "超时秒数，默认30"},
                    },
                    "required": ["command"],
                },
                risk_level="L2",
            ),
            ToolEntry(
                name="read_file",
                description="【代码检查】在允许的工作空间内读取文件内容。拒绝二进制文件和超过 1MB 的文件。替代 execute_command cat。",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "文件路径，相对于项目根目录"}
                    },
                    "required": ["path"],
                },
                risk_level="L0",
            ),
            ToolEntry(
                name="search_code",
                description="【代码检查】在工作空间内搜索代码模式（正则表达式）。返回 文件:行号:内容。替代 execute_command grep。",
                parameters={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "搜索模式（正则表达式）"},
                        "path": {
                            "type": "string",
                            "description": "搜索路径，相对于项目根目录，默认 robocode/",
                        },
                    },
                    "required": ["pattern"],
                },
                risk_level="L0",
            ),
            ToolEntry(
                name="apply_patch",
                description="【代码编辑】在允许的工作空间内应用 unified diff 补丁。拒绝受保护文件（安全策略/后端/审批/急停）。修改前需操作者审批。",
                parameters={
                    "type": "object",
                    "properties": {
                        "patch_text": {"type": "string", "description": "unified diff 格式补丁"},
                        "target_file": {"type": "string", "description": "目标文件路径"},
                    },
                    "required": ["patch_text", "target_file"],
                },
                risk_level="L1",
            ),
            ToolEntry(
                name="generate_diff_summary",
                description="【代码检查】解析 unified diff 补丁，返回变更摘要（路径、修改块数、增删行数）。只读。",
                parameters={
                    "type": "object",
                    "properties": {
                        "patch_text": {"type": "string", "description": "unified diff 格式补丁"}
                    },
                    "required": ["patch_text"],
                },
                risk_level="L0",
            ),
            ToolEntry(
                name="run_checks",
                description="【代码检查】对指定 Python 文件运行语法检查和导入检查。报告错误，绝不安装依赖。",
                parameters={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "要检查的文件路径"}
                    },
                    "required": ["file_path"],
                },
                risk_level="L0",
            ),
            ToolEntry(
                name="generate_wrapper_template",
                description="【工具创作】生成 SDK 或 ROS2 工具 wrapper 模板代码。需提供工具名、描述、SDK 方法列表或 ROS2 action。",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "工具名（Python 标识符）"},
                        "description": {"type": "string"},
                        "sdk_methods": {"type": "array", "items": {"type": "string"}},
                        "ros2_actions": {"type": "array", "items": {"type": "string"}},
                        "risk_level": {"type": "string", "enum": ["L0", "L1", "L2"]},
                        "backend": {"type": "string", "enum": ["sdk", "ros2"]},
                    },
                    "required": ["name", "description"],
                },
                risk_level="L0",
            ),
            ToolEntry(
                name="generate_wrapper_metadata",
                description="【工具创作】生成 wrapper 元数据（name/description/schema/risk/timeout/backend/dry_run）。",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "risk_level": {"type": "string"},
                        "timeout_s": {"type": "number"},
                        "backend": {"type": "string"},
                        "parameters": {"type": "object"},
                    },
                    "required": ["name", "description"],
                },
                risk_level="L0",
            ),
            ToolEntry(
                name="register_wrapper",
                description="【工具创作】注册 wrapper 为永久工具。dry_run=True 仅验证不注册（默认），dry_run=False 正式注册。",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "risk_level": {"type": "string", "enum": ["L0", "L1", "L2"]},
                        "timeout_s": {"type": "number"},
                        "backend": {"type": "string", "enum": ["sdk", "ros2"]},
                        "parameters": {"type": "object"},
                        "dry_run": {"type": "boolean"},
                    },
                    "required": ["name", "description"],
                },
                risk_level="L1",
            ),
        ]
        for entry in entries:
            self.registry.register(entry)

        # Register skills from script inventory
        for script in SCRIPT_INVENTORY:
            try:
                self.registry.register(
                    SkillEntry(
                        name=script["name"],
                        description=script["description"],
                        parameters={"type": "object", "properties": {}},
                        script_path=script["path"],
                        requires_human=script["requires_human"],
                        output_files=script["output_files"],
                        category=script.get("category", ""),
                        risk_level="L1" if script["requires_human"] else "L0",
                    )
                )
            except ValueError:
                pass

        # Register skills from robocode/skills/ folder (auto-discovered)
        self._skills = load_skills()
        _SKILL_PARAMS = {
            "6d_grasp": {
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": '自然语言抓取指令，如"抓取桌上的海绵块"',
                    }
                },
                "required": ["instruction"],
            },
        }
        for skill in self._skills.values():
            try:
                params = _SKILL_PARAMS.get(skill.name, {"type": "object", "properties": {}})
                self.registry.register(
                    SkillEntry(
                        name=skill.name,
                        description=skill.description,
                        parameters=params,
                        script_path=skill.script,
                        requires_human=skill.requires_human,
                        output_files=skill.output_files,
                        category=skill.category,
                        risk_level=skill.risk_level,
                    )
                )
            except ValueError:
                pass
            self.slash.register_skill(skill)

    def _build_handler_map(self) -> dict:
        reg = self.registry

        def list_skills(**kwargs):
            skills = reg.list_skills()
            return {
                "success": True,
                "message": f"共 {len(skills)} 个技能可用",
                "metrics": {
                    "count": len(skills),
                    "skills": [
                        {
                            "name": s.name,
                            "category": s.category,
                            "description": s.description,
                            "requires_human": s.requires_human,
                            "script_path": s.script_path,
                        }
                        for s in skills
                    ],
                },
            }

        handlers = {"list_skills": list_skills}
        handlers.update(make_motion_tools(self.backend, self.safety))
        handlers.update(make_gripper_tools(self.backend, self.safety))
        handlers.update(make_script_tools())
        handlers.update(make_codegen_tools(session_id=self._session_id))
        handlers.update(make_exec_tools())
        handlers.update(make_code_tools())
        handlers.update(make_patch_tools())
        handlers.update(make_wrapper_tools(registry=reg))
        return handlers

    async def _owner_approval_callback(
        self, tool_name: str, risk_level: str, params: dict, summary: str
    ) -> str:
        """CLI Y/N/A/S approval prompt. Called by ToolGuard during agent execution."""
        self.console.print(
            Panel(
                f"工具: {tool_name}\n"
                f"风险: {risk_level}\n"
                f"参数: {json.dumps(params, ensure_ascii=False)}\n"
                f"摘要: {summary or '(无)'}\n\n"
                "[Y] 批准本次   [N] 拒绝   [A] 本工具此后免审批   [S] 全部免审批",
                title="[bold yellow]审批[/bold yellow]",
                border_style="yellow",
            )
        )
        fd = sys.stdin.fileno()
        loop = asyncio.get_running_loop()
        if getattr(self, "_esc_watcher_active", False):
            try:
                loop.remove_reader(fd)
            except Exception:
                pass
        try:
            while True:
                ch = await loop.run_in_executor(None, sys.stdin.read, 1)
                if ch.lower() in ("y", "n", "a", "s"):
                    label = {
                        "y": "批准本次",
                        "n": "拒绝",
                        "a": "本工具此后免审批",
                        "s": "全部免审批",
                    }[ch.lower()]
                    self.console.print(f"[bold]{label}[/bold]")
                    return ch.upper()
        finally:
            if getattr(self, "_esc_watcher_active", False):
                loop.add_reader(fd, self._on_esc_stdin)

    async def run(self):
        self._show_banner()

        # SIGINT during agent execution → cancel the agent task
        # SIGINT during prompt → KeyboardInterrupt (handled by prompt_async)
        original_sigint = signal.getsignal(signal.SIGINT)

        def _sigint_handler(sig, frame):
            if self._agent_running and self._agent_task and not self._agent_task.done():
                self._agent_task.cancel()
                self.console.print("\n[yellow]⏹ 已中断 (Ctrl+C)[/yellow]")
            else:
                # Not running agent — restore original handler and re-raise
                signal.signal(signal.SIGINT, original_sigint)
                raise KeyboardInterrupt

        while self._running:
            try:
                # Set SIGINT handler for prompt phase
                signal.signal(signal.SIGINT, original_sigint)
                user_input = await self.session.prompt_async(
                    [("class:prompt", "you "), ("", "▸ ")],
                    style=PROMPT_STYLE,
                )
                user_input = user_input.strip()
            except (KeyboardInterrupt, EOFError):
                self.console.print("\n再见~")
                break
            if not user_input:
                continue

            if user_input.startswith("/"):
                self._handle_slash(user_input)
            else:
                # Install agent-phase SIGINT handler
                signal.signal(signal.SIGINT, _sigint_handler)
                await self._handle_chat(user_input)

        # Restore original signal handler
        signal.signal(signal.SIGINT, original_sigint)
        self.db.close()

    def _handle_slash(self, user_input: str):
        result = self.slash.dispatch(user_input)
        if not result.handled:
            self.console.print(Panel(f"未知命令: {user_input}", border_style="red"))
            return
        if result.estop_requested:
            self._trigger_estop()
        if result.exit_requested:
            self._running = False
        if result.action == "skill_prompt":
            asyncio.create_task(self._handle_chat(result.message))
            return
        if result.action == "resume_session":
            return
        if result.action == "approve_all":
            self.approval.approve_all()
            self.console.print("[bold green]✅ 本会话所有 L2 工具已免审批[/bold green]")
            return
        self.console.print(Panel(result.message, title="slash", border_style="blue"))

    async def _handle_chat(self, user_input: str):
        display = self.console
        provider = self.agent.provider

        original_stream = provider.stream
        provider.stream = self._make_display_stream(original_stream)
        self._start_esc_watcher()
        try:
            self._agent_running = True
            self._agent_task = asyncio.current_task()
            result = await self.agent.run_turn(user_input)
            if result:
                sys.stdout.write("\n")
                sys.stdout.flush()
        except asyncio.CancelledError:
            display.print(Panel("已中断", title="cancel", border_style="yellow"))
        except Exception as e:
            display.print(Panel(str(e), title="error", border_style="red"))
        finally:
            self._agent_running = False
            self._agent_task = None
            provider.stream = original_stream
            self._stop_esc_watcher()

    def _start_esc_watcher(self):
        """Set terminal to raw mode and watch stdin for ESC (0x1b) via asyncio."""
        try:
            fd = sys.stdin.fileno()
            self._esc_old_termios = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            os.set_blocking(fd, False)
            loop = asyncio.get_event_loop()
            self._esc_watcher_active = True
            loop.add_reader(fd, self._on_esc_stdin)
        except Exception:
            self._esc_watcher_active = False

    def _on_esc_stdin(self):
        try:
            data = os.read(sys.stdin.fileno(), 16)
            if b"\x1b" in data and self._agent_task and not self._agent_task.done():
                self._agent_task.cancel()
        except Exception:
            pass

    def _stop_esc_watcher(self):
        if not getattr(self, "_esc_watcher_active", False):
            return
        try:
            loop = asyncio.get_event_loop()
            loop.remove_reader(sys.stdin.fileno())
        except Exception:
            pass
        try:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._esc_old_termios)
        except Exception:
            pass
        self._esc_watcher_active = False

    def _make_display_stream(self, original_stream):
        display = self.console

        async def display_stream(system, messages, tools):
            async for event in original_stream(system, messages, tools):
                if event.kind == "text_delta":
                    sys.stdout.write(event.payload.get("delta", ""))
                    sys.stdout.flush()
                elif event.kind == "tool_use":
                    sys.stdout.write("\n")
                    display.print(
                        Panel(
                            json.dumps(
                                event.payload.get("input", {}), ensure_ascii=False, indent=2
                            ),
                            title=f"[bold yellow]tool: {event.payload.get('name', '?')}[/bold yellow]",
                            border_style="yellow",
                        )
                    )
                yield event

        return display_stream

    def _trigger_estop(self):
        self.backend.emergency_stop(True)
        self.console.print("[bold red]急停已触发！[/bold red]")

    def _show_banner(self):
        backend_info = f"后端: {self.settings.active_backend} ({self.settings.backend.sdk_host}:{self.settings.backend.sdk_port})"
        if self._backend_fake:
            if self._explicit_fake:
                backend_info += "\n[dim]DRY-RUN 模式（--fake），所有动作均为模拟[/dim]"
            else:
                err = getattr(self, "_backend_error", "未知错误")
                backend_info += "\n[bold red]⚠ SDK 后端连接失败！当前运行在 DRY-RUN 模式，所有动作均为模拟[/bold red]"
                backend_info += f"\n[red]原因: {err}[/red]"

        self.console.print(
            Panel(
                "[bold]robocode[/bold] v0.1.0\n"
                "Robot Natural Language Agent\n\n"
                f"{backend_info}\n"
                f"模型: {self.settings.provider.model}\n\n"
                "输入自然语言指令，或输入 /help 查看命令列表。\n"
                "提示: python -m robocode --fake  跳过硬件连接，直接进入模拟模式",
                border_style="red" if (self._backend_fake and not self._explicit_fake) else "green",
                title="robocode",
            )
        )


def main():
    import sys

    fake = "--fake" in sys.argv or "--dry-run" in sys.argv
    app = RobocodeApp(fake=fake)
    asyncio.run(app.run())


if __name__ == "__main__":
    main()
