"""资源追踪器 — 临时文件和子进程的注册与清理喵~

会话期间追踪创建的资源，会话结束统一清理。
启动时检测并清理过期残留。
"""

import os
import signal
import time
import threading
from pathlib import Path
from robocode.services.analytics.logger import get_logger

logger = get_logger("resources")

_STALE_THRESHOLD_S = 24 * 3600  # 24 小时过期阈值


class ResourceTracker:
    """追踪临时文件和子进程 PID 用于清理喵~"""

    def __init__(self):
        self._lock = threading.Lock()
        self._files: set[Path] = set()
        self._pids: set[int] = set()
        self._temp_dir = Path(__file__).resolve().parent.parent.parent / ".temp"

    # ── 注册 ──────────────────────────────────────────────────────

    def track_file(self, path: str | Path):
        """注册需要清理的文件喵~"""
        with self._lock:
            self._files.add(Path(path))

    def track_process(self, pid: int):
        """注册需要清理的子进程 PID 喵~"""
        with self._lock:
            self._pids.add(pid)

    # ── 清理 ──────────────────────────────────────────────────────

    def cleanup(self):
        """清理所有已注册的文件和子进程喵~"""
        with self._lock:
            for path in list(self._files):
                try:
                    if path.exists():
                        path.unlink()
                        logger.info("resource_cleaned", path=str(path))
                except Exception as e:
                    logger.warning("resource_cleanup_failed", path=str(path), error=str(e))
            self._files.clear()

            for pid in list(self._pids):
                try:
                    os.kill(pid, signal.SIGTERM)
                    logger.info("process_terminated", pid=pid)
                except Exception as e:
                    logger.warning("process_terminate_failed", pid=pid, error=str(e))
            self._pids.clear()

    def pending(self) -> dict:
        """返回当前已追踪的资源数量喵~"""
        with self._lock:
            return {"files": len(self._files), "processes": len(self._pids)}

    # ── 启动时脏状态检测 ──────────────────────────────────────────

    def detect_dirty_state(self) -> list[str]:
        """扫描 .temp/ 中的过期文件，自动清理并返回消息喵~"""
        messages = []
        if not self._temp_dir.exists():
            return messages

        now = time.time()
        for item in self._temp_dir.iterdir():
            if item.is_file():
                age_s = now - item.stat().st_mtime
                if age_s > _STALE_THRESHOLD_S:
                    try:
                        item.unlink()
                        messages.append(f"[dim]已清理过期文件: {item.name}[/dim]")
                    except Exception:
                        pass
                elif item.name.startswith("gen_"):
                    # 近期的生成文件仅提示，不自动清
                    pass
        return messages
