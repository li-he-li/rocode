"""Runtime cleanup — prevent unbounded growth of generated code and runtime logs."""

import time
from pathlib import Path

_ROBOCODE_DIR = Path(__file__).resolve().parent.parent  # robocode/

_GENERATED_DIR = _ROBOCODE_DIR / ".temp" / "generated"
_RUNTIME_DIR = _ROBOCODE_DIR / "log" / "runtime"

MAX_GENERATED_FILES = 50
MAX_RUNTIME_DAYS = 30


def _clean_old_files(directory: Path, max_files: int):
    """Keep only the newest max_files in directory, delete older ones."""
    if not directory.exists():
        return
    files = sorted(directory.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files[max_files:]:
        try:
            f.unlink()
        except OSError:
            pass


def _clean_old_runtime_logs(directory: Path, max_days: int):
    """Delete runtime log files older than max_days."""
    if not directory.exists():
        return
    cutoff = time.time() - max_days * 86400
    for f in directory.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            try:
                f.unlink()
            except OSError:
                pass


def run_startup_cleanup():
    """Called on RobocodeApp startup. Cleans generated code and old runtime logs."""
    _clean_old_files(_GENERATED_DIR, MAX_GENERATED_FILES)
    _clean_old_runtime_logs(_RUNTIME_DIR, MAX_RUNTIME_DAYS)
