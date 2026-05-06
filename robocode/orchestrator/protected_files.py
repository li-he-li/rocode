"""Protected file registry — files that require explicit operator approval before editing.

Phase 2 code-evolution agent must not silently modify these files.
"""

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

PROTECTED_FILES: list[str] = [
    # Safety policy — workspace limits, hardware constraints, joint limits
    "robocode/config/settings.py",
    "robocode/orchestrator/safety.py",
    # Backend adapters — hardware dispatch paths
    "robocode/backends/base.py",
    "robocode/backends/sdk_backend.py",
    # Approval gates — L2 enforcement, session auto-approval
    "robocode/orchestrator/approval.py",
    "robocode/orchestrator/tool_guard.py",
    # Emergency stop — local immediate command, bypasses LLM
    "robocode/cli/slash.py",  # /estop handler
    "robocode/cli/app.py",  # _trigger_estop, esc watcher
    # Tool registry enforcement — registration, risk levels, schemas
    "robocode/tools/registry.py",
    # Code sandbox — forbidden patterns, isolation
    "robocode/tools/codegen_tools.py",
    "robocode/tools/exec_tools.py",
]

# Resolved absolute paths for matching
PROTECTED_PATHS: set[str] = {str((_PROJECT_ROOT / p).resolve()) for p in PROTECTED_FILES}


def is_protected(file_path: str | Path) -> bool:
    """Check if a file path matches any protected file."""
    resolved = str(Path(file_path).resolve())
    return resolved in PROTECTED_PATHS


def list_protected() -> list[str]:
    """List all protected file paths (relative to project root)."""
    return list(PROTECTED_FILES)
