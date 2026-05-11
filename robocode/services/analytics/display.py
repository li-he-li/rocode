"""Rich Table rendering for /audit command views."""

from rich.columns import Columns
from rich.table import Table
from rich.panel import Panel


def render_session_list(db, voice_metrics: dict | None = None) -> Panel:
    """Recent 5 sessions with aggregated stats."""
    sessions = db.recent_sessions_with_stats(limit=5)
    if not sessions:
        return Panel("暂无审计记录", title="audit")

    table = Table(title="最近会话", header_style="bold cyan")
    table.add_column("会话 ID", style="dim", width=14)
    table.add_column("后端", width=6)
    table.add_column("状态", width=6)
    table.add_column("工具调用", justify="right")
    table.add_column("成功率", justify="right")
    table.add_column("总耗时", justify="right")

    for s in sessions:
        sid = s["id"][:8] + "..."
        total = s.get("total_calls", 0)
        success = s.get("success_calls", 0)
        rate = f"{success / total * 100:.0f}%" if total > 0 else "N/A"
        dur = f"{s.get('total_duration_ms', 0):.0f}ms"
        table.add_row(sid, s.get("backend", "?"), s.get("status", "?"), str(total), rate, dur)

    lines = [table]

    if voice_metrics:
        vo = voice_metrics.get("voice_operations", {})
        if vo.get("total", 0) > 0:
            vtable = Table(title="语音操作")
            vtable.add_column("总计", justify="right")
            vtable.add_column("成功", justify="right")
            vtable.add_column("失败", justify="right")
            vtable.add_column("平均延迟", justify="right")
            vtable.add_column("平均置信度", justify="right")
            vtable.add_row(
                str(vo["total"]),
                str(vo["success"]),
                str(vo["failure"]),
                f"{vo['avg_latency_ms']}ms",
                f"{vo['avg_confidence']:.3f}",
            )
            lines.append(vtable)

    content = Columns(lines) if len(lines) > 1 else lines[0]
    return Panel(content, title="audit")


def render_tool_stats(db, session_id: str | None = None) -> Panel:
    """Per-tool latency and success rate."""
    # Use most recent session if none specified
    if session_id is None:
        sessions = db.list_sessions(limit=1)
        if not sessions:
            return Panel("暂无会话", title="audit tools")
        session_id = sessions[0]["id"]

    latency = db.tool_latency_stats(session_id)
    success = {r["tool_name"]: r for r in db.tool_success_rate(session_id)}

    table = Table(title=f"工具统计 (会话 {session_id[:8]}...)", header_style="bold cyan")
    table.add_column("工具", style="green")
    table.add_column("调用", justify="right")
    table.add_column("成功", justify="right")
    table.add_column("失败", justify="right")
    table.add_column("P50", justify="right")
    table.add_column("P95", justify="right")
    table.add_column("平均", justify="right")

    for lr in latency:
        name = lr["tool_name"]
        sr = success.get(name, {})
        table.add_row(
            name,
            str(lr.get("call_count", 0)),
            str(sr.get("success", 0)),
            str(sr.get("failure", 0)),
            f"{lr.get('p50_ms', 0):.0f}ms",
            f"{lr.get('p95_ms', 0):.0f}ms",
            f"{lr.get('avg_ms', 0):.0f}ms",
        )

    return Panel(table, title="audit tools")


def render_safety_stats(db, session_id: str | None = None) -> Panel:
    """Safety rejection history with reason distribution."""
    if session_id is None:
        sessions = db.list_sessions(limit=1)
        if not sessions:
            return Panel("暂无会话", title="audit safety")
        session_id = sessions[0]["id"]

    rejections = db.safety_rejection_stats(session_id)

    table = Table(title=f"安全拒绝统计 (会话 {session_id[:8]}...)", header_style="bold cyan")
    table.add_column("原因", style="red")
    table.add_column("次数", justify="right")

    if not rejections:
        table.add_row("(无拒绝记录)", "-")
    else:
        for r in rejections:
            table.add_row(r.get("reason", "?"), str(r.get("count", 0)))

    return Panel(table, title="audit safety")
