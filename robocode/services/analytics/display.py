"""Rich 表格渲染 — /audit 命令的视图层喵~"""

from rich.columns import Columns
from rich.console import Group
from rich.table import Table
from rich.panel import Panel


def render_session_list(db, voice_metrics: dict | None = None) -> Panel:
    """渲染最近5个会话的聚合统计喵~"""
    sessions = db.recent_sessions_with_stats(limit=5)
    if not sessions:
        return Panel("暂无审计记录", title="audit")

    table = Table(title="最近会话", header_style="bold cyan")
    table.add_column("会话 ID", style="dim", width=14)
    table.add_column("后端", width=6)
    table.add_column("状态", width=6)
    table.add_column("工具调用", justify="right")
    table.add_column("成功率", justify="right")
    table.add_column("物理采集", justify="right")
    table.add_column("已标注", justify="right")
    table.add_column("总耗时", justify="right")

    for s in sessions:
        sid = s["id"][:8] + "..."
        total = s.get("total_calls", 0)
        success = s.get("success_calls", 0)
        rate = f"{success / total * 100:.0f}%" if total > 0 else "N/A"
        physics = str(s.get("physics_captured", 0))
        annotated = str(s.get("annotated", 0))
        dur = f"{s.get('total_duration_ms', 0):.0f}ms"
        table.add_row(
            sid,
            s.get("backend", "?"),
            s.get("status", "?"),
            str(total),
            rate,
            physics,
            annotated,
            dur,
        )

    lines = [table]

    # 语音操作统计（如果有）
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
    """渲染单会话的工具延迟和成功率喵~"""
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

    lines = [table]

    # 物理数据采集覆盖
    pstats = db.physics_stats(session_id)
    if pstats and pstats.get("total_physics", 0) > 0:
        lines.append(
            f"[dim]📊 物理数据采集: {pstats['total_physics']} 条"
            f" | 平均延时 {pstats.get('avg_duration_ms', 0):.0f}ms[/dim]"
        )

    # 标注覆盖率
    astats = db.annotation_stats(session_id)
    if astats:
        total = astats.get("total_calls", 0) or 0
        annotated = astats.get("annotated_count", 0) or 0
        coverage = f"{annotated / total * 100:.0f}%" if total > 0 else "N/A"
        lines.append(f"[dim]🏷 标注覆盖率: {annotated}/{total} ({coverage})[/dim]")

    return Panel(Group(*lines), title="audit tools")


def render_safety_stats(db, session_id: str | None = None) -> Panel:
    """渲染安全拒绝统计喵~"""
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
