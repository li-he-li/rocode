"""CLI tests — slash commands, /estop bypass, app startup."""

from robocode.cli.slash import SlashDispatcher, SlashResult, SlashCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.completion import Completion


class TestSlashDispatcher:
    def test_help_returns_info(self):
        d = SlashDispatcher()
        result = d.dispatch("/help")
        assert "帮助" in result.message or "help" in result.message.lower()
        assert result.handled is True

    def test_exit_signals_quit(self):
        d = SlashDispatcher()
        result = d.dispatch("/exit")
        assert result.exit_requested is True

    def test_status_returns_info(self):
        d = SlashDispatcher()
        result = d.dispatch("/status")
        assert result.handled is True
        assert "后端" in result.message

    def test_unknown_command_not_handled(self):
        d = SlashDispatcher()
        result = d.dispatch("/nonexistent_cmd_123")
        assert result.handled is False

    def test_plain_text_not_slash(self):
        d = SlashDispatcher()
        result = d.dispatch("not a slash command")
        assert result.handled is False

    def test_tools_returns_list(self):
        from robocode.tools.registry import ToolRegistry, ToolEntry

        reg = ToolRegistry()
        reg.register(
            ToolEntry(name="get_robot_status", description="状态", parameters={}, risk_level="L0")
        )
        reg.register(
            ToolEntry(name="move_robot_home", description="回零", parameters={}, risk_level="L1")
        )
        d = SlashDispatcher(registry=reg)
        result = d.dispatch("/tools")
        assert result.handled is True
        assert "get_robot_status" in result.message

    def test_clear_returns_info(self):
        d = SlashDispatcher()
        result = d.dispatch("/clear")
        assert result.handled is True
        assert result.clear_screen is True
        assert "上下文已清空" in result.message

    def test_audit_returns_info(self):
        d = SlashDispatcher()
        result = d.dispatch("/audit")
        assert result.handled is True
        assert "审计" in result.message

    def test_resume_with_session_id(self):
        from robocode.persistence.db import AuditDB
        import tempfile
        import os

        tmp = tempfile.mktemp(suffix=".db")
        db = AuditDB(path=tmp)
        db.initialize()
        sid = db.create_session(backend="sdk")
        try:
            d = SlashDispatcher(db=db)
            result = d.dispatch(f"/resume {sid}")
            assert result.handled is True
            assert sid[:12] in result.message or "会话" in result.message
            # No arg lists sessions
            result2 = d.dispatch("/resume")
            assert result2.handled is True
            assert result2.action == "resume_select"
            assert sid[:12] in result2.message
        finally:
            db.close()
            if os.path.exists(tmp):
                os.unlink(tmp)

    def test_backend_no_arg_shows_current(self):
        d = SlashDispatcher()
        result = d.dispatch("/backend")
        assert result.handled is True
        assert "sdk" in result.message or "SDK" in result.message

    def test_backend_with_arg_forwards_to_llm(self):
        d = SlashDispatcher()
        result = d.dispatch("/backend 怎么切换")
        assert result.handled is True
        assert result.action == "chat"
        assert "怎么切换" in result.message

    # --- chat forwarding: info commands with extra args → LLM ---

    def test_help_with_arg_forwards_to_llm(self):
        d = SlashDispatcher()
        result = d.dispatch("/help 状态命令")
        assert result.handled is True
        assert result.action == "chat"
        assert "状态命令" in result.message

    def test_status_with_arg_forwards_to_llm(self):
        d = SlashDispatcher()
        result = d.dispatch("/status 怎么查看关节")
        assert result.handled is True
        assert result.action == "chat"
        assert "怎么查看关节" in result.message

    def test_tools_with_arg_forwards_to_llm(self):
        from robocode.tools.registry import ToolRegistry, ToolEntry

        reg = ToolRegistry()
        reg.register(
            ToolEntry(name="get_robot_status", description="状态", parameters={}, risk_level="L0")
        )
        d = SlashDispatcher(registry=reg)
        result = d.dispatch("/tools L2的有哪些")
        assert result.handled is True
        assert result.action == "chat"
        assert "L2的有哪些" in result.message

    def test_action_commands_ignore_args(self):
        d = SlashDispatcher()
        assert d.dispatch("/exit 不退出").exit_requested is True
        assert d.dispatch("/estop 不急停").estop_requested is True
        assert d.dispatch("/clear 不清空").clear_screen is True

    def test_chat_if_args_no_arg_returns_direct(self):
        d = SlashDispatcher()
        result = d._chat_if_args("test", "output", "")
        assert result.action == ""
        assert result.message == "output"

    def test_chat_if_args_with_arg_forwards(self):
        d = SlashDispatcher()
        result = d._chat_if_args("test", "output", "追问")
        assert result.action == "chat"
        assert "output" in result.message
        assert "追问" in result.message


class TestSlashCompleter:
    """SlashCompleter — / 命令 Tab 补全 & 下拉预览."""

    @staticmethod
    def _completions(dispatcher, text):
        return list(SlashCompleter(dispatcher).get_completions(Document(text, len(text)), None))

    def test_bare_slash_returns_all_commands(self):
        d = SlashDispatcher()
        comps = self._completions(d, "/")
        assert len(comps) >= 10  # built-in commands
        assert all(isinstance(c, Completion) for c in comps)
        assert all(c.text.startswith("/") for c in comps)

    def test_partial_prefix_filters(self):
        d = SlashDispatcher()
        comps = self._completions(d, "/he")
        texts = {c.text for c in comps}
        assert "/help" in texts
        assert "/exit" not in texts
        # Every returned completion must start with the prefix
        assert all(c.text.startswith("/he") for c in comps)

    def test_non_slash_returns_empty(self):
        d = SlashDispatcher()
        assert self._completions(d, "hello") == []
        assert self._completions(d, "") == []

    def test_completions_carry_display_meta(self):
        d = SlashDispatcher()
        comps = self._completions(d, "/help")
        assert len(comps) == 1
        assert comps[0].display_meta is not None

    def test_get_command_list_returns_tuples(self):
        d = SlashDispatcher()
        cmds = d.get_command_list()
        assert len(cmds) >= 10
        for cmd, desc in cmds:
            assert cmd.startswith("/")
            assert isinstance(desc, str)
        # Built-in descriptions
        desc_map = dict(cmds)
        assert "显示帮助" in desc_map["/help"]
        assert "退出" in desc_map["/exit"]

    def test_skill_commands_included_in_completions(self):
        from dataclasses import dataclass

        @dataclass
        class Skill:
            name: str = "test_demo"
            description: str = "测试技能"
            requires_human: bool = False
            body: str = ""
            script: str = "test.py"
            output_files: list = None
            category: str = "test"
            risk_level: str = "L0"

        d = SlashDispatcher()
        d.register_skill(Skill())
        comps = self._completions(d, "/test")
        assert len(comps) == 1
        assert comps[0].text == "/test_demo"
        assert "测试技能" in str(comps[0].display_meta)


class TestAppRouting:
    """App-level input routing beyond dispatcher."""

    def test_unknown_slash_reported_not_sent_to_llm(self):
        from robocode.cli.slash import SlashDispatcher, SlashResult

        d = SlashDispatcher()

        def input_router(user_input: str) -> SlashResult | str:
            if user_input.startswith("/"):
                result = d.dispatch(user_input)
                if result.handled:
                    return result
                return SlashResult(
                    handled=True,
                    message=f"未知命令: {user_input}，输入 /help 查看可用命令",
                )
            return user_input

        routed = input_router("/typo")
        assert isinstance(routed, SlashResult)
        assert "未知命令" in routed.message
        assert "/typo" in routed.message

    def test_normal_text_still_goes_to_llm(self):
        from robocode.cli.slash import SlashDispatcher, SlashResult

        d = SlashDispatcher()

        def input_router(user_input: str) -> SlashResult | str:
            if user_input.startswith("/"):
                result = d.dispatch(user_input)
                if result.handled:
                    return result
                return SlashResult(
                    handled=True,
                    message=f"未知命令: {user_input}",
                )
            return user_input

        routed = input_router("hello robot")
        assert isinstance(routed, str)
        assert routed == "hello robot"


class TestEstopBypass:
    """/estop must be handled locally, never sent to LLM."""

    def test_estop_is_handled_locally(self):
        d = SlashDispatcher()
        result = d.dispatch("/estop")
        assert result.handled is True
        assert result.exit_requested is False  # estop does not exit
        assert "急停" in result.message or "estop" in result.message.lower()

    def test_estop_never_goes_to_llm(self):
        """Simulate the input routing: /estop must be intercepted before LLM."""
        d = SlashDispatcher()

        def input_router(user_input: str) -> SlashResult | str:
            if user_input.startswith("/"):
                result = d.dispatch(user_input)
                if result.handled:
                    return result  # local command, never reaches LLM
            return user_input  # goes to LLM

        # /estop is intercepted, does not reach LLM
        routed = input_router("/estop")
        assert isinstance(routed, SlashResult)
        assert routed.handled is True

        # normal text goes to LLM
        routed = input_router("move to home")
        assert isinstance(routed, str)
        assert routed == "move to home"
