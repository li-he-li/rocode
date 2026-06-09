"""运行时 JSONL 日志 — 结构化日志记录工具调用/代码生成/脚本执行喵~

写入 robocode/log/runtime/YYYY-MM-DD.jsonl，每行一个 JSON 对象。
"""

import json
import time
import threading
from pathlib import Path

_ROBOCODE_DIR = Path(__file__).resolve().parent.parent  # robocode/
_LOG_DIR = _ROBOCODE_DIR / "log" / "runtime"
_LOCK = threading.Lock()  # 线程安全写入锁


def _log_path() -> Path:
    """获取当日日志文件路径，自动创建目录喵~"""
    from datetime import date

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR / f"{date.today().isoformat()}.jsonl"


def log_event(event_type: str, **fields):
    """追加一条结构化事件到当日运行时日志喵~"""
    record = {"ts": time.time(), "event": event_type, **fields}
    try:
        with _LOCK:
            with open(_log_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass  # 日志写入失败不影响主流程


def log_tool_call(
    tool_name: str,
    risk_level: str,
    params: dict,
    result: dict,
    duration_ms: float = 0,
    session_id: str = "",
):
    """记录工具调用事件喵~"""
    log_event(
        "tool_call",
        tool_name=tool_name,
        risk_level=risk_level,
        params=params,
        result=result,
        duration_ms=duration_ms,
        session_id=session_id,
    )


def log_codegen(
    code: str,
    summary: str,
    result: dict,
    duration_ms: float = 0,
    session_id: str = "",
    saved_path: str = "",
):
    """记录代码生成事件喵~"""
    log_event(
        "codegen",
        summary=summary,
        code=code,
        result=result,
        duration_ms=duration_ms,
        session_id=session_id,
        saved_path=saved_path,
    )


def log_script(
    script_name: str,
    cmd: list[str],
    returncode: int,
    stdout: str,
    stderr: str,
    duration_ms: float = 0,
    session_id: str = "",
):
    """记录脚本执行事件喵~"""
    log_event(
        "script",
        script_name=script_name,
        cmd=cmd,
        returncode=returncode,
        stdout=stdout[-2000:],
        stderr=stderr[-2000:],
        duration_ms=duration_ms,
        session_id=session_id,
    )
