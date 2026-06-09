"""运行时清理 — 防止生成代码和运行时日志无限增长喵~"""

import time
from pathlib import Path

_ROBOCODE_DIR = Path(__file__).resolve().parent.parent  # robocode/
_GENERATED_DIR = _ROBOCODE_DIR / ".temp" / "generated"
_RUNTIME_DIR = _ROBOCODE_DIR / "log" / "runtime"

MAX_GENERATED_FILES = 5  # 最多保留5个生成文件
MAX_RUNTIME_DAYS = 30  # 运行日志最多保留30天


def _clean_old_files(directory: Path, max_files: int):
    """保留最新的 max_files 个文件，删除更旧的喵~"""
    if not directory.exists():
        return
    files = sorted(directory.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files[max_files:]:
        try:
            f.unlink()
        except OSError:
            pass


def _clean_old_runtime_logs(directory: Path, max_days: int):
    """删除超过 max_days 天的运行时日志喵~"""
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
    """应用启动时调用 — 清理生成代码和旧运行时日志喵~"""
    _clean_old_files(_GENERATED_DIR, MAX_GENERATED_FILES)
    _clean_old_runtime_logs(_RUNTIME_DIR, MAX_RUNTIME_DAYS)
