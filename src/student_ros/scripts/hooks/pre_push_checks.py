#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST_PATH = ROOT / "src" / "episode_controller" / "test"


def _is_ci() -> bool:
    return os.getenv("CI", "").strip().lower() in {"1", "true", "yes", "on"}


def _run(command: list[str], cwd: Path = ROOT) -> int:
    print("+", " ".join(command))
    completed = subprocess.run(command, cwd=str(cwd), check=False)
    return completed.returncode


def _has_mypy_config(root: Path) -> bool:
    ini_candidates = [root / "mypy.ini", root / ".mypy.ini"]
    if any(path.exists() for path in ini_candidates):
        return True

    text_candidates = [root / "pyproject.toml", root / "setup.cfg", root / "tox.ini"]
    for path in text_candidates:
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        if "[tool.mypy]" in content or "[mypy]" in content:
            return True
    return False


def main() -> int:
    if _is_ci():
        print("CI environment detected, skip local pre-push hooks.")
        return 0

    if not TEST_PATH.exists():
        print(f"Test path not found: {TEST_PATH}. Skip test step.")
        return 0

    if _run([sys.executable, "-m", "pytest", "--version"]) != 0:
        print("pytest is required for pre-push checks. Please install project test deps.")
        return 1

    rc = _run([sys.executable, "-m", "pytest", "-q", str(TEST_PATH)])
    if rc != 0:
        return rc

    if _has_mypy_config(ROOT):
        if _run([sys.executable, "-m", "mypy", "--version"]) != 0:
            print("mypy config detected, but mypy is not installed.")
            return 1
        rc = _run([sys.executable, "-m", "mypy", "src"])
        if rc != 0:
            return rc
    else:
        print("No mypy configuration detected, skip type-check step.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
