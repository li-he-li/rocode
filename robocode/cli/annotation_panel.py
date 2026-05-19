"""Annotation panel UI — rich Panel rendering + raw stdin Y/N/Q input."""

import sys
import asyncio
from rich.console import Console
from rich.panel import Panel
from robocode.agent.annotation import (
    ANNOTATION_SCHEMA,
    FAILURE_RULES,
    AnnotationResult,
)


class AnnotationPanel:
    """Interactive annotation panel using raw stdin (Y/N/Q).

    Reuses the same raw-stdin pattern as _owner_approval_callback.
    """

    def __init__(self, collector, console: Console | None = None, experience_reader=None):
        self._collector = collector
        self._console = console or Console()
        self._experience_reader = experience_reader

    async def run(self) -> list[AnnotationResult]:
        """Run annotation panel for all pending tool calls.

        Returns list of completed AnnotationResults.
        """
        pending = self._collector.get_pending()
        if not pending:
            self._console.print("[dim]本轮无待标注项[/dim]")
            return []

        results: list[AnnotationResult] = []
        for item in pending:
            tool_call_id = item["tool_call_id"]
            tool_name = item["tool_name"]
            params = item.get("params", {})
            category = self._collector.get_category(tool_name)

            result = await self._annotate_one(tool_call_id, tool_name, category, params)
            if result is not None:
                results.append(result)
                self._collector.collect(
                    tool_call_id=tool_call_id,
                    category=result.category,
                    choices=result.choices,
                    is_failure=result.is_failure,
                    free_text=result.free_text,
                )
            else:
                self._collector.skip(tool_call_id)

        return results

    async def _annotate_one(
        self, tool_call_id: int, tool_name: str, category: str, params: dict
    ) -> AnnotationResult | None:
        """Annotate a single tool call. Returns None if user skips."""
        schema = ANNOTATION_SCHEMA.get(category, ANNOTATION_SCHEMA["general"])
        dims = list(schema.keys())
        if not dims:
            return None

        choices = {}
        self._show_header(tool_name, category, params)

        for dim_name in dims:
            options = schema[dim_name]
            choice = await self._ask_dimension(dim_name, options)
            if choice == "Q":
                # Skip all remaining
                return None
            elif choice == "N":
                # Skip this dimension, leave unset
                continue
            else:
                choices[dim_name] = choice

        if not choices:
            return None

        is_failure = FAILURE_RULES.is_failure(category, choices)
        free_text = await self._ask_free_text()

        return AnnotationResult(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            category=category,
            choices=choices,
            is_failure=is_failure,
            free_text=free_text,
        )

    def _show_header(self, tool_name: str, category: str, params: dict):
        param_str = ", ".join(f"{k}={v}" for k, v in params.items()) if params else "(无参数)"
        body = f"[bold]{tool_name}[/bold]  [{category}]\n参数: {param_str}"

        # Show related experience hints if available
        if self._experience_reader and self._experience_reader.has_experiences():
            visible = self._experience_reader.get_visible_experiences()
            related = [e for e in visible if e.get("category") == category]
            if related:
                body += "\n\n[dim]相关经验:[/dim]"
                for e in related[:3]:
                    body += f"\n[dim]  - {e.get('category')}/{e.get('filename')} (confidence={e.get('confidence', 0):.0%})[/dim]"

        self._console.print(Panel(body, border_style="blue"))

    async def _ask_dimension(self, dim_name: str, options: list[str]) -> str:
        """Show dimension options, return selected value or N/Q."""
        opts_str = "  ".join(f"[{i}] {o}" for i, o in enumerate(options))
        self._console.print(f"\n[bold yellow]{dim_name}?[/bold yellow]")
        self._console.print(f"  {opts_str}")
        self._console.print("  [N] 跳过  [Q] 跳过全部剩余", style="dim")

        while True:
            ch = await self._read_char()
            if ch is None:
                continue
            cl = ch.lower()
            if cl in ("n", "q"):
                return cl.upper()
            if cl.isdigit():
                idx = int(cl)
                if 0 <= idx < len(options):
                    self._console.print(f"  → [green]{options[idx]}[/green]")
                    return options[idx]

    async def _ask_free_text(self) -> str:
        """Optional free text input. Enter to skip."""
        self._console.print("\n[bold yellow]补充说明?[/bold yellow] [dim](Enter 跳过)[/dim]")
        try:
            loop = asyncio.get_running_loop()
            chars = []
            while True:
                ch = await loop.run_in_executor(None, sys.stdin.read, 1)
                if ch == "\n":
                    text = "".join(chars).strip()
                    if text:
                        self._console.print(f"  → [green]{text}[/green]")
                    return text
                elif ch == "\x1b":
                    return ""
                elif ch and len(ch) == 1:
                    sys.stdout.write(ch)
                    sys.stdout.flush()
                    chars.append(ch)
        except Exception:
            return ""

    async def _read_char(self) -> str | None:
        """Read a single character from stdin."""
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, sys.stdin.read, 1)
        except Exception:
            return None

    @staticmethod
    def get_failure_summary(results: list[AnnotationResult]) -> list[dict]:
        """Extract failure summaries for injection into agent context."""
        failures = []
        for r in results:
            if r.is_failure:
                failed_dims = {
                    dim: val
                    for dim, val in r.choices.items()
                    if val
                    not in ("成功", "正确", "准确", "平稳", "无异常", "合适", "无", "部分成功")
                }
                failures.append(
                    {
                        "tool_name": r.tool_name,
                        "failed_dimensions": ", ".join(
                            f"{dim}={val}" for dim, val in failed_dims.items()
                        ),
                    }
                )
        return failures
