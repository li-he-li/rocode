"""Annotation panel UI — summary view, single feedback text for all pending items."""

import sys
import asyncio
import termios
import os
from rich.console import Console
from rich.panel import Panel
from robocode.agent.annotation import (
    AnnotationResult,
)

_FAILURE_KEYWORDS = [
    "失败",
    "错误",
    "偏差",
    "偏了",
    "偏移",
    "振动",
    "抖动",
    "碰撞",
    "掉落",
    "没抓到",
    "抓空",
    "异常",
    "超限",
    "不到位",
    "不准确",
    "不平稳",
    "噪音",
    "卡顿",
    "超时",
    "报错",
    "失控",
    "撞",
    "停不下来",
    "太快",
    "太慢",
    "不动",
    "没反应",
]


def _detect_failure(text: str) -> bool:
    lower = text.lower()
    for kw in _FAILURE_KEYWORDS:
        idx = lower.find(kw)
        if idx == -1:
            continue
        prefix = lower[max(0, idx - 1) : idx]
        if prefix in ("不", "没", "无", "非"):
            continue
        return True
    return False


async def _read_multiline_tty() -> str:
    """Read multi-line text from /dev/tty. Empty line (double Enter) to finish."""
    loop = asyncio.get_running_loop()
    for path in ("/dev/tty", "/dev/stdin"):
        try:
            fd = os.open(path, os.O_RDONLY)
        except (OSError, IOError):
            continue
        try:
            old = termios.tcgetattr(fd)
            new = termios.tcgetattr(fd)
            new[3] |= termios.ICANON | termios.ECHO | termios.IEXTEN
            termios.tcsetattr(fd, termios.TCSADRAIN, new)
            try:
                lines: list[str] = []
                with os.fdopen(fd, "r", encoding="utf-8", closefd=False) as f:
                    first = (await loop.run_in_executor(None, f.readline)).rstrip("\n\r")
                    if not first:
                        return ""
                    lines.append(first)
                    while True:
                        line = (await loop.run_in_executor(None, f.readline)).rstrip("\n\r")
                        if not line:
                            break
                        lines.append(line)
                return "\n".join(lines)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
                os.close(fd)
        except (OSError, IOError, EOFError):
            os.close(fd)
            continue
    return ""


class AnnotationPanel:
    """Summary annotation — shows all pending tool calls, asks for one feedback."""

    def __init__(self, collector, console: Console | None = None, experience_reader=None):
        self._collector = collector
        self._console = console or Console()
        self._experience_reader = experience_reader

    async def run(self) -> tuple[list[AnnotationResult], str]:
        """Collect feedback. Returns (results, free_text).

        If there are pending tool calls, annotates them all with the same
        feedback. If none, still collects free-text feedback for the session.
        """
        pending = self._collector.get_pending()

        # ── Show header ────────────────────────────────────────────
        if pending:
            item_lines = [
                f"  [{i + 1}] [bold]{p['tool_name']}[/bold]  "
                f"({self._collector.get_category(p['tool_name'])})"
                for i, p in enumerate(pending)
            ]
            self._console.print(
                Panel(
                    f"[bold]本轮共 {len(pending)} 个操作[/bold]\n\n"
                    + "\n".join(item_lines)
                    + "\n\n请一次总结所有操作的效果。",
                    border_style="blue",
                )
            )
        else:
            self._console.print(
                Panel(
                    "[bold]本轮为纯对话，无工具操作[/bold]\n\n可以输入任何反馈、建议、经验总结。",
                    border_style="blue",
                )
            )

        # ── Read multi-line feedback ────────────────────────────────
        prompt = "请描述（多行输入，空行结束）:" if pending else "请输入（多行输入，空行结束）:"
        self._console.print(f"\n[bold cyan]{prompt}[/bold cyan]")
        sys.stdout.write("> ")
        sys.stdout.flush()

        text = (await self._read_input_line()).strip()

        if text.upper() == "Q" or not text:
            if pending:
                for p in pending:
                    self._collector.skip(p["tool_call_id"])
            self._console.print("[dim]已跳过[/dim]")
            return [], ""

        self._console.print(f"  → [green]{text}[/green]")

        # ── No pending items: return raw text only ──────────────────
        if not pending:
            return [], text

        # ── Has pending items: annotate all with same feedback ──────
        is_failure = _detect_failure(text)
        if is_failure:
            self._console.print("  [yellow]⚠ 检测到问题关键词，标记为失败[/yellow]")
        else:
            self._console.print("  [green]✓ 标记为成功[/green]")

        results: list[AnnotationResult] = []
        for item in pending:
            result = AnnotationResult(
                tool_call_id=item["tool_call_id"],
                tool_name=item["tool_name"],
                category=self._collector.get_category(item["tool_name"]),
                choices={},
                is_failure=is_failure,
                free_text=text,
            )
            results.append(result)
            self._collector.collect(
                tool_call_id=item["tool_call_id"],
                category=result.category,
                choices=result.choices,
                is_failure=result.is_failure,
                free_text=result.free_text,
            )

        return results, text

    async def _read_input_line(self) -> str:
        return await _read_multiline_tty()

    @staticmethod
    def get_failure_summary(results: list[AnnotationResult]) -> list[dict]:
        """Extract failure summaries for injection into agent context."""
        failures = []
        for r in results:
            if r.is_failure:
                failures.append(
                    {
                        "tool_name": r.tool_name,
                        "failed_dimensions": r.free_text,
                    }
                )
        return failures
