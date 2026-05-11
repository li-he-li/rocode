"""Resource tracker — registry for temp files and subprocesses.

Tracks resources created during a session. On session end, cleans up
registered resources. On startup, detects and cleans stale resources.
"""

import os
import signal
import time
import threading
from pathlib import Path
from robocode.services.analytics.logger import get_logger

logger = get_logger("resources")

_STALE_THRESHOLD_S = 24 * 3600  # 24 hours


class ResourceTracker:
    """Tracks files and PIDs for cleanup."""

    def __init__(self):
        self._lock = threading.Lock()
        self._files: set[Path] = set()
        self._pids: set[int] = set()
        self._temp_dir = Path(__file__).resolve().parent.parent.parent / ".temp"

    # ── registration ─────────────────────────────────────────────────

    def track_file(self, path: str | Path):
        with self._lock:
            self._files.add(Path(path))

    def track_process(self, pid: int):
        with self._lock:
            self._pids.add(pid)

    # ── cleanup ──────────────────────────────────────────────────────

    def cleanup(self):
        """Clean up all registered files and kill tracked processes."""
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
        """Return current tracked resource counts."""
        with self._lock:
            return {
                "files": len(self._files),
                "processes": len(self._pids),
            }

    # ── startup dirty state detection ─────────────────────────────────

    def detect_dirty_state(self) -> list[str]:
        """Scan .temp/ for stale files. Returns list of messages."""
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
                    # Recent generated files — notify
                    pass  # Don't auto-clean recent files
        return messages
