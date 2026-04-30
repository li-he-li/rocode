#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

ALLOWED_TYPES = (
    "feat",
    "fix",
    "docs",
    "style",
    "refactor",
    "test",
    "chore",
    "perf",
    "ci",
    "build",
    "revert",
)

CONVENTIONAL_RE = re.compile(
    r"^(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)"
    r"(\([^)]+\))?(!)?: .+$"
)


def _first_meaningful_line(path: Path) -> str:
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for raw_line in f:
            line = raw_line.strip().lstrip("\ufeff")
            if line and not line.startswith("#"):
                return line
    return ""


def _normalize_prefix(message: str) -> str:
    for prefix in ("fixup! ", "squash! "):
        if message.startswith(prefix):
            return message[len(prefix) :]
    return message


def _is_valid(message: str) -> bool:
    if message.startswith("Merge "):
        return True
    if message.startswith("Revert \""):
        return True
    return bool(CONVENTIONAL_RE.match(message))


def main() -> int:
    if len(sys.argv) < 2:
        print("commit-msg hook requires a commit message file path.")
        return 1

    commit_msg_file = Path(sys.argv[1])
    message = _first_meaningful_line(commit_msg_file)
    normalized = _normalize_prefix(message)

    if _is_valid(normalized):
        return 0

    print("Invalid commit message format.")
    print(
        "Expected: type(scope): description  or  type: description "
        "(optional ! before ':')."
    )
    print(f"Allowed types: {', '.join(ALLOWED_TYPES)}")
    print(f"Got: {message!r}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
