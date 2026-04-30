#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str]) -> None:
    print("+", " ".join(command))
    subprocess.check_call(command, cwd=str(ROOT))


def main() -> int:
    _run([sys.executable, "-m", "pip", "install", "--upgrade", "pre-commit"])
    _run(
        [
            sys.executable,
            "-m",
            "pre_commit",
            "install",
            "--install-hooks",
            "--hook-type",
            "pre-commit",
            "--hook-type",
            "pre-push",
            "--hook-type",
            "commit-msg",
        ]
    )
    print("Git hooks are installed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
