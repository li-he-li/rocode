"""CLI main entry — prompt_toolkit REPL with slash commands, streaming, and panels."""

from rich.console import Console
from rich.panel import Panel
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style

from robocode.cli.slash import SlashDispatcher, SlashResult

PROMPT_STYLE = Style.from_dict(
    {
        "prompt": "#00ff00 bold",
        "separator": "#666666",
    }
)


class RobocodeApp:
    def __init__(self, backend_status: str = "SDK (localhost:12345)"):
        self.console = Console()
        self.session = PromptSession(history=InMemoryHistory())
        self.slash = SlashDispatcher()
        self.backend_status = backend_status
        self._running = True

    def run(self):
        self._show_banner()
        while self._running:
            try:
                user_input = self.session.prompt(
                    [("class:prompt", "you "), ("", "▸ ")],
                    style=PROMPT_STYLE,
                ).strip()
            except (KeyboardInterrupt, EOFError):
                self.console.print("\n再见~")
                break
            if not user_input:
                continue
            result = self._route(user_input)
            self._display_result(result)

    def _route(self, user_input: str) -> "SlashResult | str":
        if user_input.startswith("/"):
            result = self.slash.dispatch(user_input)
            if result.handled:
                if result.estop_requested:
                    self._trigger_estop()
                if result.exit_requested:
                    self._running = False
                return result
            return SlashResult(
                handled=True,
                message=f"未知命令: {user_input}，输入 /help 查看可用命令",
            )
        return user_input

    def _trigger_estop(self):
        self.console.print("[bold red]急停已触发！[/bold red]")

    def _display_result(self, result):
        if isinstance(result, SlashResult):
            self.console.print(Panel(result.message, title="slash", border_style="blue"))
        elif isinstance(result, str):
            self.console.print(Panel(f"[dim]→ LLM 收到:[/dim] {result[:200]}", border_style="dim"))

    def _show_banner(self):
        self.console.print(
            Panel(
                "[bold]robocode[/bold] v0.1.0\n"
                "Robot Natural Language Agent\n\n"
                f"后端: {self.backend_status}\n"
                "模型: DeepSeek V4 Pro\n\n"
                "输入自然语言指令，或输入 /help 查看命令列表。",
                border_style="green",
                title="robocode",
            )
        )


def main():
    app = RobocodeApp()
    app.run()


if __name__ == "__main__":
    main()
