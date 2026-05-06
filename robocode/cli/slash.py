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
    def __init__(self, db=None, registry=None, robot_backend=None):
        self._commands: dict[str, callable] = {}
        self._skills_help: list[str] = []
        self._db = db
        self._registry = registry
        self._robot_backend = robot_backend
        # Built-in commands
        for cmd, handler in [
            ("/help", self._help),
            ("/exit", self._exit),
            ("/status", self._status),
            ("/tools", self._tools),
            ("/audit", self._audit),
            ("/clear", self._clear),
            ("/resume", self._resume),
            ("/backend", self._backend),
            ("/estop", self._estop),
            ("/approve-all", self._approve_all),
        ]:
            self._commands[cmd] = handler

    def register_skill(self, skill):
        """Register a skill as a slash command. /<name> shows info, /<name> <指令> sends skill+instruction to LLM."""
        cmd = f"/{skill.name}"
        tag = "[需人]" if skill.requires_human else "[自动]"
        self._skills_help.append(f"  {cmd}  {tag}  {skill.description}")

        def handler(arg, s=skill):
            if not arg.strip():
                # No args: show skill info
                return SlashResult(
                    handled=True,
                    message=f"## {s.name}\n\n{s.description}\n\n### 指引\n{s.body[:1500]}\n\n启动: `python {s.script}`",
                )

            # Has args: pack skill context + user instruction → forward to LLM
            return SlashResult(
                handled=True,
                action="skill_prompt",
                message=(
                    f"【技能】{s.name}: {s.description}\n"
                    f"【人工要求】{'需要' if s.requires_human else '无需'}人工操作\n"
                    f"【启动脚本】python {s.script}\n\n"
                    f"--- 技能指引 ---\n"
                    f"{s.body}\n"
                    f"--- 用户指令 ---\n"
                    f"{arg.strip()}\n\n"
                    f"请根据上述技能指引，执行用户的指令。如需人工操作，请引导用户逐步完成。"
                ),
            )

        self._commands[cmd] = handler

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
        lines = [
            "系统命令：",
            "  /help        显示帮助",
            "  /exit        退出",
            "  /status      显示机器人和系统状态",
            "  /tools       列出所有工具",
            "  /audit       查看审计日志",
            "  /clear       清空对话上下文",
            "  /resume <id> 从检查点恢复会话",
            "  /backend     显示/切换后端",
            "  /estop       立即急停",
            "  /approve-all 本会话全部免审批",
        ]
        if self._skills_help:
            lines.append("")
            lines.append("技能 (/<技能名> 查看详情)：")
            lines.extend(self._skills_help)
        return SlashResult(handled=True, message="\n".join(lines))

    def _exit(self, _arg: str) -> SlashResult:
        return SlashResult(handled=True, exit_requested=True, message="再见~")

    def _status(self, _arg: str) -> SlashResult:
        lines = ["## 系统状态\n"]
        if self._robot_backend is not None:
            try:
                st = self._robot_backend.get_status()
                lines.append(
                    f"后端: {st.backend} | 连接: {'是' if st.connected else '否'} | 急停: {'是' if st.estop_active else '否'}"
                )
                if st.motor_angles:
                    lines.append(f"关节: {[round(a, 1) for a in st.motor_angles]}")
                if st.pose:
                    lines.append(f"位姿: {[round(p, 1) for p in st.pose]}")
            except Exception:
                lines.append("后端: 无法获取状态")
        else:
            lines.append("后端: 未配置")
        return SlashResult(handled=True, message="\n".join(lines))

    def _tools(self, _arg: str) -> SlashResult:
        if self._registry is None:
            return SlashResult(handled=True, message="工具注册表未初始化")

        by_risk: dict[str, list[str]] = {"L0": [], "L1": [], "L2": []}
        for entry in self._registry.list_tools():
            by_risk.get(entry.risk_level, []).append(entry.name)
        for entry in self._registry.list_skills():
            by_risk.get(entry.risk_level, []).append(f"{entry.name}*")

        lines = ["## 工具列表\n"]
        for level in ("L0", "L1", "L2"):
            names = by_risk.get(level, [])
            if names:
                lines.append(f"{level} ({len(names)}): {', '.join(sorted(names))}")
        lines.append("\n* = 技能（可能需要人工操作）")
        return SlashResult(handled=True, message="\n".join(lines))

    def _audit(self, _arg: str) -> SlashResult:
        if self._db is None:
            return SlashResult(handled=True, message="审计日志: 数据库未初始化")
        try:
            sessions = self._db.list_sessions(limit=5)
            lines = ["## 审计日志\n"]
            for s in sessions:
                sid = s["id"]
                lines.append(f"### 会话 {sid[:8]}... ({s['backend']})")
                calls = self._db.list_tool_calls(sid, limit=20)
                lines.append(f"  工具调用 ({len(calls)} 条):")
                for c in calls[-5:]:
                    lines.append(f"    - [{c['risk_level']}] {c['tool_name']}")
                approvals = self._db.list_approvals(sid)
                lines.append(f"  审批记录 ({len(approvals)} 条):")
                for a in approvals[-5:]:
                    status = "通过" if a["approved"] else "拒绝"
                    lines.append(f"    - {a['tool_name']}: {status}")
                lines.append("")
            return SlashResult(handled=True, message="\n".join(lines))
        except Exception as e:
            return SlashResult(handled=True, message=f"审计日志查询失败: {e}")

    def _clear(self, _arg: str) -> SlashResult:
        return SlashResult(handled=True, clear_screen=True, message="上下文已清空")

    def _resume(self, arg: str) -> SlashResult:
        if self._db is None:
            return SlashResult(handled=True, message="数据库未初始化，无法恢复会话")

        arg = arg.strip()
        if not arg:
            # No session ID — list recent sessions
            try:
                sessions = self._db.list_sessions(limit=10)
                if not sessions:
                    return SlashResult(handled=True, message="没有历史会话")
                lines = ["## 最近会话\n"]
                for s in sessions:
                    ck = self._db.get_latest_checkpoint(s["id"])
                    step_info = f", 步骤: {ck['step_index']}" if ck else ""
                    lines.append(
                        f"  {s['id'][:12]}... 后端:{s['backend']} 状态:{s['status']}{step_info}"
                    )
                lines.append("\n输入 /resume <id> 恢复指定会话")
                return SlashResult(handled=True, message="\n".join(lines))
            except Exception as e:
                return SlashResult(handled=True, message=f"查询会话失败: {e}")

        # Specific session ID — show details
        try:
            session = self._db.get_session(arg)
            if session is None:
                # Try prefix match
                sessions = self._db.list_sessions(limit=100)
                matches = [s for s in sessions if s["id"].startswith(arg)]
                if not matches:
                    return SlashResult(handled=True, message=f"会话 {arg[:12]}... 不存在")
                session = matches[0]

            calls = self._db.list_tool_calls(session["id"], limit=50)
            approvals = self._db.list_approvals(session["id"])
            checkpoint = self._db.get_latest_checkpoint(session["id"])

            lines = [
                f"## 会话 {session['id'][:12]}...",
                f"后端: {session['backend']} | 状态: {session['status']}",
                f"工具调用: {len(calls)} 条 | 审批: {len(approvals)} 条",
            ]
            if checkpoint:
                lines.append(f"最后检查点: 步骤 {checkpoint.get('step_index', 0)}")
            if calls:
                lines.append("最近调用:")
                for c in calls[-5:]:
                    lines.append(f"  [{c['risk_level']}] {c['tool_name']}")

            lines.append(f"\n会话 {session['id'][:12]}... 的上下文已就绪，可以继续操作。")
            return SlashResult(handled=True, action="resume_session", message="\n".join(lines))
        except Exception as e:
            return SlashResult(handled=True, message=f"恢复会话失败: {e}")

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

    def _approve_all(self, _arg: str) -> SlashResult:
        return SlashResult(
            handled=True,
            action="approve_all",
            message="本会话所有 L2 工具已免审批。可通过 /approve-all 再次切换。",
        )
