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
from prompt_toolkit.filters import has_completions
from prompt_toolkit.key_binding import KeyBindings

from robocode.cli.slash import SlashDispatcher, SlashCompleter
from robocode.cli.skill_loader import load_skills
from robocode.cli.voice import VoiceController, VoiceState
from robocode.agent.core import AgentLoop
from robocode.agent.physics_collector import PhysicsCollector
from robocode.agent.annotation import AnnotationCollector
from robocode.agent.experience_reader import ExperienceReader
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
from robocode.services.analytics.db import AuditDB
from robocode.services.analytics.logger import setup_logging, get_logger
from robocode.services.analytics.metrics import MetricsCollector
from robocode.services.analytics.resource_tracker import ResourceTracker

PROMPT_STYLE = Style.from_dict({"prompt": "#00ff00 bold"})


class RobocodeApp:
    def __init__(self, fake: bool = False):
        self.console = Console()
        self._explicit_fake = fake
        self._backend_error = ""

        # Metrics collector (before voice, so voice can use it)
        self.metrics = MetricsCollector()

        # Voice controller — preloads model in background thread
        self._voice = VoiceController(metrics=self.metrics)
        self._voice.set_on_result(self._on_voice_result)

        kb = KeyBindings()

        @kb.add("escape")
        def _(event):
            if self._agent_task and not self._agent_task.done():
                self._agent_task.cancel()
                self.console.print("\n[yellow]⏹ 已中断[/yellow]")

        @kb.add("f2")
        def _(event):
            if self._agent_running:
                return
            state = self._voice.state
            if state == VoiceState.LOADING:
                self.console.print("[dim]🎤 语音模型加载中，请稍候...[/dim]")
            elif state in (VoiceState.READY, VoiceState.IDLE):
                self._voice.start_recording()
            elif state == VoiceState.RECORDING:
                self._voice.stop_recording(trigger="f2")

        @kb.add("enter", filter=has_completions)
        def _(event):
            buf = event.current_buffer
            if buf.complete_state:
                buf.apply_completion(buf.complete_state.current_completion)

        self.session = PromptSession(
            history=InMemoryHistory(),
            key_bindings=kb,
            refresh_interval=0.3,
            complete_while_typing=True,
        )
        self._running = True
        self._agent_task = None
        self._agent_running = False

        self.settings = Settings()
        setup_logging()
        self._logger = get_logger("cli")
        run_startup_cleanup()

        # Resource tracker
        self._resources = ResourceTracker()
        for msg in self._resources.detect_dirty_state():
            self.console.print(msg)
        self.db = AuditDB()
        self.db.initialize()
        self._session_id = self.db.create_session(backend=self.settings.active_backend)
        self._startup_cleanup()
        self.slash = SlashDispatcher(db=self.db)
        self.session.completer = SlashCompleter(self.slash)

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
            metrics=self.metrics,
        )

        # Physics data collector
        self.physics_collector = PhysicsCollector(
            backend=self.backend,
            db=self.db,
            session_id=self._session_id,
            metrics=self.metrics,
        )

        # Annotation collector
        self.annotation_collector = AnnotationCollector(
            db=self.db,
            session_id=self._session_id,
        )

        # Experience reader — loads index at startup
        self.experience_reader = ExperienceReader()

        # Agent
        self.agent = AgentLoop(
            provider=DeepSeekProvider(self.settings),
            tool_handlers=self._build_handler_map(),
            tool_schemas=self.registry.all_schemas(),
            guard=self.tool_guard,
            risk_levels=risk_levels,
            db=self.db,
            session_id=self._session_id,
            metrics=self.metrics,
            physics_collector=self.physics_collector,
            annotation_collector=self.annotation_collector,
            experience_reader=self.experience_reader,
        )

        # Wire registry + backend + voice into slash dispatcher (created before them)
        self.slash._registry = self.registry
        self.slash._robot_backend = self.backend
        self.slash._voice = self._voice
        self.slash._annotation_collector = self.annotation_collector
        self.slash._agent = self.agent

    def _startup_cleanup(self):
        """Clean up interrupted sessions, expired sessions, and requeue failed items."""
        try:
            log = get_logger("app")
            # Find sessions that were not properly closed
            sessions = self.db.list_sessions(limit=50)
            cleaned = 0
            for s in sessions:
                if s.get("status") == "active" and s["id"] != self._session_id:
                    self.db.cleanup_interrupted_session(s["id"])
                    cleaned += 1
            if cleaned:
                log.info("startup_interrupted_sessions_cleaned", count=cleaned)
            # Delete sessions older than 7 days
            expired = self.db.cleanup_old_sessions(ttl_days=7)
            if expired:
                log.info("startup_expired_sessions_cleaned", count=expired)
            # Delete empty sessions (0 tool calls, except current)
            empty = self.db.cleanup_empty_sessions(current_session_id=self._session_id)
            if empty:
                log.info("startup_empty_sessions_cleaned", count=empty)
        except Exception:
            pass

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
                name="move_path",
                description="沿连续路径运动：一次传入多个 [x,y,z] 路点，内部用直线插值依次执行，消除多步调用间的停顿。用于画圆、弧线等平滑轨迹",
                parameters={
                    "type": "object",
                    "properties": {
                        "waypoints": {
                            "type": "array",
                            "items": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 3,
                                "maxItems": 3,
                            },
                            "minItems": 1,
                            "maxItems": 200,
                        },
                        "speed_ratio": {"type": "number"},
                        "rotation": {"type": "array", "items": {"type": "number"}},
                    },
                    "required": ["waypoints"],
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
                description="【L2 需审批】在主机上执行单条命令（不支持管道|重定向|链式;）。危险命令硬拦截。复杂 shell 操作请用 generate_and_run_sdk_code。",
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
        self._loop = asyncio.get_running_loop()
        self._show_banner()
        self._check_unclosed_sessions()

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
                    bottom_toolbar=self._bottom_toolbar,
                )
                user_input = user_input.strip()
            except (KeyboardInterrupt, EOFError):
                self.console.print("\n再见~")
                await self._run_exp_manage()
                break
            if not user_input:
                continue

            if user_input.startswith("/"):
                await self._handle_slash(user_input, _sigint_handler)
            elif self._agent_running:
                self.console.print("[dim]⏳ Agent 正在执行中，请等待...[/dim]")
            else:
                # Install agent-phase SIGINT handler
                signal.signal(signal.SIGINT, _sigint_handler)
                await self._handle_chat(user_input)

        # Restore original signal handler
        signal.signal(signal.SIGINT, original_sigint)
        self._logger.info("session_ended", session_id=self._session_id)
        self._resources.cleanup()
        self.db.close_session(self._session_id)
        self._voice.shutdown()
        self.db.close()

    def _trigger_estop(self):
        try:
            self.backend.emergency_stop(True)
            self.console.print("[bold red]⚠ 急停已执行[/bold red]")
        except Exception:
            self.console.print("[bold red]⚠ 急停失败（后端不可用）[/bold red]")

    async def _handle_slash(self, user_input: str, sigint_handler):
        result = self.slash.dispatch(user_input)
        if not result.handled:
            self.console.print(Panel(f"未知命令: {user_input}", border_style="red"))
            return
        if result.estop_requested:
            self._trigger_estop()
        if result.exit_requested:
            await self._run_exp_manage()
            self._running = False
        if result.action in ("skill_prompt", "chat"):
            signal.signal(signal.SIGINT, sigint_handler)
            await self._handle_chat(result.message)
            return
        if result.action == "resume_session":
            self._restore_session(result.message)
            return
        if result.action == "resume_select":
            await self._handle_resume_select(result.message)
            return
        if result.action == "approve_all":
            self.approval.approve_all()
            self.console.print("[bold green]✅ 本会话所有 L2 工具已免审批[/bold green]")
            return
        if result.action == "annotation_panel":
            await self._run_annotation_panel()
            return
        if result.action == "exit_with_annotations":
            await self._handle_exit_with_annotations(int(result.message))
            return
        if result.action == "exp_manage":
            await self._run_exp_manage()
            return
        self.console.print(Panel(result.message, title="slash", border_style="blue"))

    async def _handle_chat(self, user_input: str, from_voice: bool = False):
        display = self.console
        provider = self.agent.provider

        original_stream = provider.stream
        provider.stream = self._make_display_stream(original_stream)
        if not from_voice:
            self._start_esc_watcher()
        try:
            self._agent_running = True
            self._agent_task = asyncio.current_task()
            result = await self.agent.run_turn(user_input)
            if result:
                sys.stdout.write("\n")
                sys.stdout.flush()
            # Auto-prompt for annotation after LLM completes a task
            if result and not from_voice:
                pending_count = self.annotation_collector.count_unannotated()
                if pending_count > 0:
                    await self._prompt_annotation_after_task(pending_count)
        except asyncio.CancelledError:
            display.print(Panel("已中断", title="cancel", border_style="yellow"))
        except Exception as e:
            display.print(Panel(str(e), title="error", border_style="red"))
        finally:
            self._agent_running = False
            self._agent_task = None
            provider.stream = original_stream
            if not from_voice:
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

    def _on_voice_result(self, text: str):
        """Called from background thread when transcription completes."""
        if hasattr(self, "_loop"):
            self._loop.call_soon_threadsafe(self._handle_voice_result_safe, text)

    def _handle_voice_result_safe(self, text: str):
        """Runs on main event loop thread. Displays result and dispatches to agent."""
        if text:
            self.console.print(f"[bold green]🎤 →[/bold green] {text}")
            if not self._agent_running:
                asyncio.create_task(self._handle_chat(text, from_voice=True))
        else:
            self.console.print("[dim]🎤 未检测到语音，请重试[/dim]")

    def _bottom_toolbar(self):
        state = self._voice.state
        if state == VoiceState.RECORDING:
            dots = [".  ", ".. ", "...", " ..", "  ."]
            frame = getattr(self, "_voice_dot_frame", 0) % len(dots)
            self._voice_dot_frame = frame + 1
            return f"🔴 录制中{dots[frame]}"
        elif state == VoiceState.TRANSCRIBING:
            return "⏳ 识别中..."
        elif state == VoiceState.LOADING:
            return "⏳ 语音模型加载中..."
        elif state == VoiceState.IDLE:
            return ""
        elif state == VoiceState.READY:
            return ""
        return ""

    async def _handle_resume_select(self, msg: str):
        """Interactive session selection with arrow keys."""
        import json as _json
        import tty
        import termios
        from rich.live import Live
        from rich.table import Table
        from rich.text import Text

        try:
            sessions = _json.loads(msg)
        except Exception:
            self.console.print("[red]会话列表解析失败[/red]")
            return

        n = len(sessions)
        if n == 0:
            self.console.print("[dim]没有历史会话[/dim]")
            return

        selected_idx = 0
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)

        def build_table() -> Table:
            table = Table(title="最近会话", header_style="bold cyan", show_lines=False)
            table.add_column("", width=2)
            table.add_column("会话 ID", style="dim", width=14)
            table.add_column("后端", width=6)
            table.add_column("状态", width=6)
            table.add_column("调用", justify="right")
            table.add_column("成功率", justify="right")
            for i, s in enumerate(sessions):
                sel = "▸" if i == selected_idx else ""
                style = "bold cyan" if i == selected_idx else "dim"
                table.add_row(
                    Text(sel, style="bold cyan"),
                    Text(s["id"][:12] + "...", style=style),
                    Text(s["backend"], style=style),
                    Text(s["status"], style=style),
                    Text(str(s["total_calls"]), style=style),
                    Text(s["success_rate"], style=style),
                )
            return table

        try:
            tty.setcbreak(fd)
            loop = asyncio.get_running_loop()

            with Live(build_table(), console=self.console, refresh_per_second=10) as live:
                while True:
                    ch = await loop.run_in_executor(None, os.read, fd, 3)

                    if ch == b"q" or ch == b"\x03":
                        self.console.print("[dim]已取消[/dim]")
                        return

                    if ch in (b"\r", b"\n"):
                        break

                    if ch == b"\x1b[A":
                        selected_idx = (selected_idx - 1) % n
                        live.update(build_table())
                    elif ch == b"\x1b[B":
                        selected_idx = (selected_idx + 1) % n
                        live.update(build_table())

        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

        # Restore the selected session
        try:
            selected = self.db.get_session(sessions[selected_idx]["id"])
            if selected:
                result = self.slash._build_resume_result(selected)
                if result.action == "resume_session":
                    self._restore_session(result.message)
                else:
                    self.console.print(f"[yellow]{result.message}[/yellow]")
            else:
                self.console.print("[red]会话不存在[/red]")
        except Exception as e:
            self.console.print(f"[red]恢复失败: {e}[/red]")

    def _restore_session(self, msg: str):
        """Restore agent context from a checkpoint."""
        try:
            data = json.loads(msg)
            session_id = data["session_id"]
            context_json = data.get("context_json", "")

            if context_json:
                from robocode.agent.context import ContextMemory

                self.agent.context = ContextMemory.from_json(context_json)
                self._session_id = session_id
                self.tool_guard.set_session_id(session_id)
                self.agent._session_id = session_id

            self.console.print(
                Panel(
                    f"会话: {session_id[:12]}...\n"
                    f"后端: {data.get('backend', '?')}\n"
                    f"工具调用: {data.get('calls', 0)} 条\n"
                    f"检查点步骤: {data.get('step_index', 0)}\n\n"
                    "[yellow]⚠ 机械臂状态需重新获取（/status）[/yellow]",
                    title="[bold green]会话已恢复[/bold green]",
                    border_style="green",
                )
            )
            self._logger.info("session_restored", session_id=session_id)
        except Exception:
            self._logger.exception("session_restore_failed")
            self.console.print("[red]会话恢复失败[/red]")

    def _check_unclosed_sessions(self):
        """Detect unclosed sessions at startup and show hint."""
        try:
            recent = self.db.recent_sessions_with_stats(limit=3)
            unclosed = [s for s in recent if s.get("status") == "active"]
            if unclosed:
                s = unclosed[0]
                self.console.print(
                    f"[dim]上次会话 {s['id'][:8]}... 未正常关闭，输入 /resume 恢复[/dim]"
                )
        except Exception:
            pass

    async def _prompt_annotation_after_task(self, pending_count: int):
        """Prompt user to annotate after LLM finishes a task."""
        self.console.print(
            f"\n[dim]任务完成。标注本轮 {pending_count} 个操作？"
            f"[[green]Y[/green]/n/[[green]Enter[/green]][/dim] "
        )
        loop = asyncio.get_running_loop()
        try:
            ch = await loop.run_in_executor(None, sys.stdin.read, 1)
            if ch.lower() in ("y", "\n", "\r"):
                await self._run_annotation_panel()
            else:
                self.console.print("[dim]跳过标注（稍后可用 /done 标注）[/dim]")
        except Exception:
            pass

    async def _run_annotation_panel(self):
        """Launch annotation panel for pending tool calls."""
        from robocode.cli.annotation_panel import AnnotationPanel

        panel = AnnotationPanel(
            self.annotation_collector,
            console=self.console,
            experience_reader=self.experience_reader,
        )
        results = await panel.run()

        if results:
            failures = AnnotationPanel.get_failure_summary(results)
            if failures:
                for f in failures:
                    self.agent.inject_failure_annotation(
                        f["tool_name"],
                        [f["failed_dimensions"]],
                    )
                self.console.print(
                    f"[yellow]⚠ {len(failures)} 个操作标注为失败，反馈已注入会话[/yellow]"
                )
            total = len(results)
            self.console.print(f"[green]✅ {total} 条已标注[/green]")
            # Auto-trigger experience generation after annotation
            await self._run_exp_manage()
            # Update experience confidence based on annotation feedback
            await self._apply_confidence_feedback(results)

    async def _apply_confidence_feedback(self, results):
        """Update experience confidence based on annotation results.

        Success raises confidence of experiences in the same category by +0.03.
        Failure lowers confidence by -0.05.
        """
        from robocode.agent.experience_manager import ExperienceManager

        if not self.experience_reader or not self.experience_reader.has_experiences():
            return

        mgr = ExperienceManager(db=self.db, session_id=self._session_id)
        visible = self.experience_reader.get_visible_experiences()

        # Group results by category: failure -> -0.05, success -> +0.03
        cat_adj = {}
        for r in results:
            cat = r.category
            if cat not in cat_adj:
                cat_adj[cat] = 0.0
            cat_adj[cat] += -0.05 if r.is_failure else 0.03

        updated = 0
        for exp in visible:
            exp_cat = exp.get("category", "")
            if exp_cat not in cat_adj:
                continue
            filename = exp.get("filename", "")
            if not filename:
                continue
            delta = min(0.1, max(-0.15, round(cat_adj[exp_cat], 2)))
            if abs(delta) < 0.01:
                continue
            new_conf = max(0.1, min(0.95, exp.get("confidence", 0.5) + delta))
            mgr.update_experience(
                exp_cat,
                filename,
                frontmatter_updates={"confidence": round(new_conf, 2)},
            )
            updated += 1

        if updated:
            self.console.print(f"[dim]🔄 {updated} 条经验置信度已更新[/dim]")

    async def _run_exp_manage(self):
        """Run experience manager to analyze data across all sessions and manage experience files.

        Pipeline: rule-based analysis → LLM reflection → merge into experience files.
        """
        from robocode.agent.experience_manager import ExperienceManager
        from robocode.agent.reflector import Reflector, deduplicate_bullets
        from robocode.agent.experience_filesystem import (
            EXPERIENCE_ROOT,
            write_experience,
            rebuild_index,
            backup_before_update,
        )

        mgr = ExperienceManager(db=self.db, session_id="")

        self.console.print("[bold]经验管家运行中...[/bold]")

        # ── Step 1: Rule-based analysis ──
        physics = mgr.analyze_physics()
        annotations = mgr.process_annotations()
        call_flows = mgr.analyze_call_flow()

        has_data = physics or annotations or call_flows

        # ── Step 2: LLM reflection (after rule analysis, before writing) ──
        bullets: list[str] = []
        if has_data:
            try:
                reflector = Reflector(provider=self.agent.provider, max_bullets=8)
                bullets = await reflector.reflect(
                    physics=physics,
                    annotations=annotations,
                    call_flows=call_flows,
                )
                if bullets:
                    self.console.print(f"[dim]💡 反思产出 {len(bullets)} 条洞察[/dim]")
            except Exception:
                self.console.print("[dim]⚠ LLM 反思失败，跳过反思层[/dim]")

        # ── Step 3: Write experience files (rule results + deduplicated bullets) ──

        if physics:
            for tool_name, data in physics.items():
                filename = f"{tool_name}-angle-deviation.md"
                existing = EXPERIENCE_ROOT / "physics" / filename
                confidence = min(0.5 + len(data.get("speed_groups", {})) * 0.1, 0.9)
                data_points = data.get("total_data_points", 0)

                tool_bullets: list[str] | None = None
                if bullets:
                    tool_bullets = [
                        b for b in bullets if tool_name in b or "[PARAM]" in b or "[CAUTION]" in b
                    ]
                    if existing.exists():
                        existing_bullets = ExperienceManager.extract_existing_bullets(existing)
                        tool_bullets = deduplicate_bullets(tool_bullets, existing_bullets)

                if existing.exists():
                    existing_fm = mgr._read_frontmatter(existing)
                    old_conf = existing_fm.get("confidence", confidence)
                    old_dp = existing_fm.get("data_points", 0)
                    confidence = round((old_conf + confidence) / 2, 2)
                    data_points = old_dp + data_points
                    if not tool_bullets and existing.exists():
                        tool_bullets = ExperienceManager.extract_existing_bullets(existing)

                fm, body = mgr.create_experience(
                    category="physics",
                    domain="angle-deviation",
                    title=f"{tool_name} 角度偏差分析",
                    data={tool_name: data},
                    confidence=confidence,
                    data_points=data_points,
                    bullets=tool_bullets,
                )
                backup_before_update("physics", filename)
                write_experience("physics", filename, fm, body)
                self.db.insert_experience_log(
                    "experience_created" if not existing.exists() else "experience_updated",
                    file_path=f"physics/{filename}",
                    details={
                        "confidence": confidence,
                        "data_points": data_points,
                        "bullets": len(tool_bullets or []),
                    },
                )
                marker = "[yellow]~[/yellow]" if existing.exists() else "[green]+[/green]"
                self.console.print(f"  {marker} physics/{filename}")

        if annotations:
            for category, cat_data in annotations.items():
                if not cat_data.get("failures") and not cat_data.get("successes"):
                    continue
                filename = f"{category}-experience.md"
                existing = EXPERIENCE_ROOT / category / filename
                confidence = 0.6
                data_points = cat_data.get("total", 0)

                cat_bullets: list[str] | None = None
                if bullets:
                    cat_bullets = [
                        b
                        for b in bullets
                        if f"[{category}]" in b.lower()
                        or "[PATTERN]" in b
                        or "[CAUTION]" in b
                        or "[L1]" in b
                        or "[L2]" in b
                    ]
                    if existing.exists():
                        existing_bullets = ExperienceManager.extract_existing_bullets(existing)
                        cat_bullets = deduplicate_bullets(cat_bullets, existing_bullets)

                if existing.exists():
                    existing_fm = mgr._read_frontmatter(existing)
                    confidence = round((existing_fm.get("confidence", 0.6) + confidence) / 2, 2)
                    data_points = existing_fm.get("data_points", 0) + data_points
                    if not cat_bullets and existing.exists():
                        cat_bullets = ExperienceManager.extract_existing_bullets(existing)

                fm, body = mgr.create_experience(
                    category=category,
                    domain=f"{category}-best-practices",
                    title=f"{category} 操作经验",
                    data=None,
                    confidence=confidence,
                    data_points=data_points,
                    annotations={category: cat_data},
                    call_flows=call_flows,
                    bullets=cat_bullets,
                )
                backup_before_update(category, filename)
                write_experience(category, filename, fm, body)
                self.db.insert_experience_log(
                    "experience_created" if not existing.exists() else "experience_updated",
                    file_path=f"{category}/{filename}",
                    details={
                        "confidence": confidence,
                        "data_points": data_points,
                        "bullets": len(cat_bullets or []),
                    },
                )
                marker = "[yellow]~[/yellow]" if existing.exists() else "[green]+[/green]"
                self.console.print(f"  {marker} {category}/{filename}")

        # Merge similar experiences and prune stale ones
        merged = mgr.merge_experiences()
        if merged:
            self.console.print(f"[dim]🔄 {merged} 组经验已合并[/dim]")
        pruned = mgr.prune_experiences()
        if pruned:
            self.console.print(f"[dim]🗑 {pruned} 条低置信度经验已归档[/dim]")

        rebuild_index()
        if has_data:
            self.db.mark_physics_processed()
            self.db.mark_annotations_processed()
        self.console.print("[green]✅ 经验整理完成[/green]")

    async def _handle_exit_with_annotations(self, unannotated: int):
        """Prompt user to annotate before exit. Always runs experience manager."""
        self.console.print(f"\n[yellow]有 {unannotated} 条未标注操作，现在标注？[Y/n][/yellow]")
        loop = asyncio.get_running_loop()
        try:
            ch = await loop.run_in_executor(None, sys.stdin.read, 1)
            if ch.lower() == "y":
                await self._run_annotation_panel()
            else:
                # Still run experience manager on exit
                await self._run_exp_manage()
        except Exception:
            pass
        self._running = False

    def _get_voice_status_text(self) -> str:
        state = self._voice.state
        if state == VoiceState.LOADING:
            return "语音: 加载中..."
        elif state == VoiceState.READY:
            info = self._voice.model_info
            device = info.get("device", "?").upper()
            return f"语音: small ({device}) ✓"
        elif state == VoiceState.UNAVAILABLE:
            return "语音: 不可用"
        return "语音: 就绪"

    def _show_banner(self):
        backend_info = f"后端: {self.settings.active_backend} ({self.settings.backend.sdk_host}:{self.settings.backend.sdk_port})"
        if self._backend_fake:
            if self._explicit_fake:
                backend_info += "\n[dim]DRY-RUN 模式（--fake），所有动作均为模拟[/dim]"
            else:
                err = getattr(self, "_backend_error", "未知错误")
                backend_info += "\n[bold red]⚠ SDK 后端连接失败！当前运行在 DRY-RUN 模式，所有动作均为模拟[/bold red]"
                backend_info += f"\n[red]原因: {err}[/red]"

        voice_status = self._get_voice_status_text()
        self.console.print(
            Panel(
                "[bold]robocode[/bold] v0.1.0\n"
                "Robot Natural Language Agent\n\n"
                f"{backend_info}\n"
                f"模型: {self.settings.provider.model}\n"
                f"{voice_status}\n\n"
                "输入自然语言指令，或输入 /help 查看命令列表。\n"
                "提示: python -m robocode --fake  跳过硬件连接，直接进入模拟模式",
                border_style="red" if (self._backend_fake and not self._explicit_fake) else "green",
                title="robocode",
            )
        )


def main():
    fake = "--fake" in sys.argv or "--dry-run" in sys.argv
    app = RobocodeApp(fake=fake)
    asyncio.run(app.run())


if __name__ == "__main__":
    main()
