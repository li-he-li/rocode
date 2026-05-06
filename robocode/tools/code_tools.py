"""Workspace-limited code inspection tools — read_file, search_code.

Replaces generic shell cat/grep/find via execute_command for code reading.
All operations constrained to configured workspace roots.
"""

import re
from pathlib import Path
from robocode.utils.models import ToolResult

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

WORKSPACE_ROOTS = [
    _PROJECT_ROOT / "robocode",
    _PROJECT_ROOT / "src",
    _PROJECT_ROOT / "tests",
]

BINARY_EXTENSIONS = {
    ".bin",
    ".safetensors",
    ".whl",
    ".npy",
    ".pt",
    ".pth",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tiff",
    ".so",
    ".o",
    ".a",
    ".dylib",
    ".dll",
    ".pyc",
    ".pyo",
    ".pyd",
    ".stl",
    ".obj",
    ".step",
    ".iges",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".pdf",
    ".doc",
    ".docx",
    ".db",
    ".db-journal",
    ".DS_Store",
}

MAX_FILE_SIZE = 1_000_000  # 1 MB


def _resolve_inside_workspace(path: str) -> Path | None:
    """Resolve path and return absolute Path if within workspace, else None."""
    p = Path(path)
    if not p.is_absolute():
        p = (_PROJECT_ROOT / p).resolve()
    else:
        p = p.resolve()

    # Must be under one of the workspace roots
    for root in WORKSPACE_ROOTS:
        try:
            p.relative_to(root.resolve())
            return p
        except ValueError:
            continue
    return None


def _is_binary(file_path: Path) -> bool:
    """Check if file is binary by extension."""
    return file_path.suffix.lower() in BINARY_EXTENSIONS


def read_file(*, path: str, **kwargs) -> dict:
    """Read a file within workspace roots. Rejects binary files and files >1MB."""
    resolved = _resolve_inside_workspace(path)
    if resolved is None:
        return ToolResult(
            success=False,
            message=f"路径超出工作空间: {path}",
        ).model_dump(mode="json")

    if not resolved.exists():
        return ToolResult(
            success=False,
            message=f"文件不存在: {path}",
        ).model_dump(mode="json")

    if resolved.is_dir():
        return ToolResult(
            success=False,
            message=f"路径是目录而非文件: {path}",
        ).model_dump(mode="json")

    if _is_binary(resolved):
        return ToolResult(
            success=False,
            message=f"二进制文件，拒绝读取: {resolved.suffix}",
            metrics={"path": str(resolved), "kind": "binary"},
        ).model_dump(mode="json")

    size = resolved.stat().st_size
    if size > MAX_FILE_SIZE:
        return ToolResult(
            success=False,
            message=f"文件过大 ({size / 1e6:.1f}MB > {MAX_FILE_SIZE / 1e6:.0f}MB)，拒绝读取",
            metrics={"path": str(resolved), "size": size, "kind": "large"},
        ).model_dump(mode="json")

    try:
        content = resolved.read_text(encoding="utf-8")
        return ToolResult(
            success=True,
            message=content,
            metrics={"path": str(resolved), "size": size, "lines": content.count("\n") + 1},
        ).model_dump(mode="json")
    except UnicodeDecodeError:
        return ToolResult(
            success=False,
            message="文件不是 UTF-8 文本（可能是二进制）",
            metrics={"path": str(resolved), "size": size, "kind": "binary"},
        ).model_dump(mode="json")


def search_code(*, pattern: str, path: str = "robocode/", **kwargs) -> dict:
    """Search for pattern in files under a workspace path. Returns file:line:content."""
    root = _resolve_inside_workspace(path)
    if root is None:
        return ToolResult(
            success=False,
            message=f"搜索路径超出工作空间: {path}",
        ).model_dump(mode="json")

    if not root.exists():
        return ToolResult(
            success=False,
            message=f"搜索路径不存在: {path}",
        ).model_dump(mode="json")

    if root.is_file():
        targets = [root]
    else:
        targets = [p for p in root.rglob("*") if p.is_file()]

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return ToolResult(
            success=False,
            message=f"正则表达式无效: {e}",
        ).model_dump(mode="json")

    matches: list[str] = []
    files_scanned = 0

    for fpath in targets:
        if _is_binary(fpath):
            continue
        if fpath.stat().st_size > MAX_FILE_SIZE:
            continue
        try:
            for lineno, line in enumerate(fpath.read_text(encoding="utf-8").splitlines(), 1):
                if regex.search(line):
                    rel = str(fpath.relative_to(_PROJECT_ROOT))
                    matches.append(f"{rel}:{lineno}: {line.strip()[:200]}")
                    if len(matches) >= 200:
                        break
        except (UnicodeDecodeError, OSError):
            continue
        files_scanned += 1
        if len(matches) >= 200:
            break

    return ToolResult(
        success=True,
        message=f"找到 {len(matches)} 处匹配 (扫描 {files_scanned} 个文件)",
        metrics={
            "pattern": pattern,
            "path": str(root.relative_to(_PROJECT_ROOT)),
            "match_count": len(matches),
            "files_scanned": files_scanned,
            "matches": matches,
        },
    ).model_dump(mode="json")


def make_code_tools() -> dict:
    return {
        "read_file": read_file,
        "search_code": search_code,
    }
