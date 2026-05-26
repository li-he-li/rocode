"""Patch editing tools — workspace-limited patch application, diff summary, check runner.

Phase 2 code evolution: the agent can propose patches, the system validates and applies
them only within workspace roots, never touching protected files without explicit approval.
"""

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from robocode.utils.models import ToolResult
from robocode.orchestrator.protected_files import is_protected

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

WORKSPACE_ROOTS = [
    _PROJECT_ROOT / "robocode",
    _PROJECT_ROOT / "src",
    _PROJECT_ROOT / "tests",
]


def _resolve_inside_workspace(file_path: str) -> Path | None:
    p = Path(file_path)
    if not p.is_absolute():
        p = (_PROJECT_ROOT / p).resolve()
    else:
        p = p.resolve()
    for root in WORKSPACE_ROOTS:
        try:
            p.relative_to(root.resolve())
            return p
        except ValueError:
            continue
    return None


@dataclass
class _Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str] = field(default_factory=list)  # lines starting with ' ', '-', '+'


def _parse_patch(patch_text: str) -> dict | None:
    """Parse unified diff. Returns {path, hunks: [{old_start, old_count, new_start, new_count, lines}]} or None."""
    lines = patch_text.splitlines()
    hunk_header = re.compile(r"^@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@")

    path = None
    hunks = []
    current_hunk = None

    for line in lines:
        if line.startswith("--- "):
            continue
        if line.startswith("+++ "):
            path = line[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            continue
        m = hunk_header.match(line)
        if m:
            old_start = int(m.group(1))
            old_count = int(m.group(2)) if m.group(2) else 1
            new_start = int(m.group(3))
            new_count = int(m.group(4)) if m.group(4) else 1
            current_hunk = _Hunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
            )
            hunks.append(current_hunk)
            continue
        if current_hunk is not None and line and line[0] in (" ", "-", "+"):
            current_hunk.lines.append(line)

    if not path or not hunks:
        return None
    return {"path": path, "hunks": hunks}


def _apply_hunks(original_lines: list[str], hunks: list[_Hunk]) -> list[str] | None:
    """Apply hunks to original lines. Returns modified lines or None on mismatch."""
    result = list(original_lines)
    # Apply hunks in reverse order to keep line numbers stable
    for hunk in reversed(hunks):
        old_start = hunk.old_start - 1  # 0-based
        old_count = hunk.old_count

        # Extract context + deletions from hunk lines
        expected_old = []
        new_lines = []
        for hline in hunk.lines:
            if hline[0] == " ":
                expected_old.append(hline[1:])
                new_lines.append(hline[1:])
            elif hline[0] == "-":
                expected_old.append(hline[1:])
            elif hline[0] == "+":
                new_lines.append(hline[1:])

        # Verify old content matches
        actual_old = result[old_start : old_start + len(expected_old)]
        if actual_old != expected_old:
            return None

        # Replace: remove old range, insert new lines
        result[old_start : old_start + old_count] = new_lines

    return result


def generate_diff_summary(patch_text: str) -> dict:
    """Parse a unified diff and return a structured summary."""
    parsed = _parse_patch(patch_text)
    if parsed is None:
        return {"valid": False, "error": "无法解析补丁格式"}

    additions = 0
    deletions = 0
    for hunk in parsed["hunks"]:
        for line in hunk.lines:
            if line.startswith("+") and not line.startswith("+++"):
                additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1

    return {
        "valid": True,
        "path": parsed["path"],
        "hunks": len(parsed["hunks"]),
        "additions": additions,
        "deletions": deletions,
    }


def apply_patch(*, patch_text: str, target_file: str, **kwargs) -> dict:
    """Apply a unified diff patch to a file within workspace roots.

    Rejects: files outside workspace, protected files, non-existent targets.
    """
    resolved = _resolve_inside_workspace(target_file)
    if resolved is None:
        return ToolResult(
            success=False,
            message=f"目标文件超出工作空间: {target_file}",
        ).model_dump(mode="json")

    if is_protected(str(resolved)):
        return ToolResult(
            success=False,
            message=f"目标文件受保护，修改需操作者显式审批: {target_file}",
            metrics={"target_file": target_file, "protected": True},
        ).model_dump(mode="json")

    if not resolved.exists():
        return ToolResult(
            success=False,
            message=f"目标文件不存在: {target_file}",
        ).model_dump(mode="json")

    # Parse the patch
    parsed = _parse_patch(patch_text)
    if parsed is None:
        return ToolResult(
            success=False,
            message="补丁格式无效，无法解析",
        ).model_dump(mode="json")

    # Read original file
    original = resolved.read_text(encoding="utf-8")
    original_lines = original.splitlines()

    # Apply hunks
    modified = _apply_hunks(original_lines, parsed["hunks"])
    if modified is None:
        return ToolResult(
            success=False,
            message="补丁应用失败：上下文不匹配，文件可能已被其他修改变更",
            metrics={"target_file": target_file},
        ).model_dump(mode="json")

    # Write back
    result_text = "\n".join(modified) + "\n"
    resolved.write_text(result_text, encoding="utf-8")

    # Generate summary
    summary = generate_diff_summary(patch_text)
    return ToolResult(
        success=True,
        message=f"补丁已应用: {target_file} (+{summary['additions']}/-{summary['deletions']} 行)",
        metrics={
            "target_file": target_file,
            "hunks": len(parsed["hunks"]),
            "additions": summary["additions"],
            "deletions": summary["deletions"],
        },
    ).model_dump(mode="json")


def run_checks(*, file_path: str, **kwargs) -> dict:
    """Run import and syntax checks on a Python file. Reports errors, never installs deps."""
    p = Path(file_path)
    if not p.is_absolute():
        p = (_PROJECT_ROOT / p).resolve()

    workspace_file = _resolve_inside_workspace(file_path)
    if workspace_file is None:
        return ToolResult(
            success=False,
            message=f"文件超出工作空间，需操作者批准: {file_path}",
            metrics={"file_path": file_path, "outside_workspace": True},
        ).model_dump(mode="json")

    results = {}

    # Syntax check via compile
    try:
        source = p.read_text(encoding="utf-8")
        compile(source, str(p), "exec")
        results["syntax_check"] = {"passed": True, "error": ""}
    except SyntaxError as e:
        results["syntax_check"] = {
            "passed": False,
            "error": f"行 {e.lineno}: {e.msg}",
        }
        results["import_check"] = {"passed": False, "error": "语法错误，跳过导入检查"}
        return results
    except Exception as e:
        results["syntax_check"] = {"passed": False, "error": str(e)}
        return results

    # Import check via subprocess (isolated)
    try:
        proc = subprocess.run(
            [
                "python3",
                "-I",
                "-c",
                f"import py_compile; py_compile.compile({str(p)!r}, doraise=True)",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(_PROJECT_ROOT),
        )
        results["import_check"] = {
            "passed": proc.returncode == 0,
            "error": proc.stderr.strip()[-500:] if proc.returncode != 0 else "",
        }
    except subprocess.TimeoutExpired:
        results["import_check"] = {"passed": False, "error": "导入检查超时"}
    except Exception as e:
        results["import_check"] = {"passed": False, "error": str(e)}

    return results


def make_patch_tools() -> dict:
    return {
        "apply_patch": apply_patch,
        "generate_diff_summary": generate_diff_summary,
        "run_checks": run_checks,
    }
