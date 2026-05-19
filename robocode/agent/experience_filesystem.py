"""Experience filesystem — write, backup, archive, and index experience files.

Experience files are Markdown + YAML frontmatter, stored under robocode/experience/.
Operations are protected: update backs up current version, archive never deletes.
"""

import re
import time
import shutil
from pathlib import Path
from robocode.services.analytics.logger import get_logger

logger = get_logger("experience_filesystem")

EXPERIENCE_ROOT = Path(__file__).resolve().parent.parent / "experience"

CATEGORIES = ["physics", "motion", "gripper", "grasp", "code", "script", "general"]


def _validate_path_component(name: str, *, allow_empty: bool = False) -> None:
    """Reject path traversal characters in category or filename components."""
    if not allow_empty and not name:
        raise ValueError("path component must not be empty")
    if ".." in name or "/" in name or "\\" in name:
        raise ValueError(f"Invalid path component: {name!r}")


def _read_frontmatter_confidence(filepath: Path) -> float | None:
    """Extract confidence value from a file's YAML frontmatter."""
    try:
        content = filepath.read_text(encoding="utf-8")[:2000]
        m = re.search(r"^confidence:\s*([\d.]+)", content, re.MULTILINE)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return None


def _extract_bullets_from_file(filepath: Path, max_bullets: int = 3) -> list[str]:
    """Extract reflection bullets from ## 建议 section of an experience file."""
    try:
        content = filepath.read_text(encoding="utf-8")
        body_start = 0
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                body_start = end + 3
        body = content[body_start:]
        in_section = False
        bullets: list[str] = []
        for line in body.split("\n"):
            stripped = line.strip()
            if stripped.startswith("## "):
                in_section = stripped == "## 建议"
                continue
            if in_section and stripped.startswith("- [") and "]" in stripped:
                bullets.append(stripped)
                if len(bullets) >= max_bullets:
                    break
        return bullets
    except Exception:
        return []


def _extract_title_from_file(filepath: Path) -> str:
    """Extract the # title from an experience file body."""
    try:
        content = filepath.read_text(encoding="utf-8")
        body_start = 0
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                body_start = end + 3
        for line in content[body_start:].split("\n"):
            stripped = line.strip()
            if stripped.startswith("# ") and not stripped.startswith("## "):
                return stripped[2:].strip()
    except Exception:
        pass
    return ""


def write_experience(
    category: str,
    filename: str,
    frontmatter: dict,
    body: str,
    base_dir: Path | None = None,
) -> Path:
    """Write an experience file with YAML frontmatter + Markdown body.

    If file already exists, call backup_before_update() first.
    Returns the written file path.
    """
    _validate_path_component(category)
    _validate_path_component(filename)
    root = base_dir or EXPERIENCE_ROOT
    cat_dir = root / category
    cat_dir.mkdir(parents=True, exist_ok=True)
    filepath = cat_dir / filename

    lines = _build_frontmatter(frontmatter)
    lines.append("")
    lines.append(body)
    filepath.write_text("\n".join(lines), encoding="utf-8")

    logger.info("experience_file_written", file_path=str(filepath), category=category)
    return filepath


def backup_before_update(category: str, filename: str, base_dir: Path | None = None):
    """Backup current version to _history/<filename>.<timestamp>.md before overwriting."""
    _validate_path_component(category)
    _validate_path_component(filename)
    root = base_dir or EXPERIENCE_ROOT
    src = root / category / filename
    if not src.exists():
        return

    ts = time.strftime("%Y-%m-%d.%H%M")
    dst = root / "_history" / f"{filename}.{ts}.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    logger.info("experience_backup_created", source=str(src), backup=str(dst))


def archive_file(category: str, filename: str, base_dir: Path | None = None):
    """Move file to _archive/<YYYY-MM-DD>/ — never deletes."""
    _validate_path_component(category)
    _validate_path_component(filename)
    root = base_dir or EXPERIENCE_ROOT
    src = root / category / filename
    if not src.exists():
        return

    date_str = time.strftime("%Y-%m-%d")
    dst_dir = root / "_archive" / date_str
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst_dir / filename))
    logger.info("experience_archived", file_path=str(src), archive_dir=str(dst_dir))


def rebuild_index(base_dir: Path | None = None):
    """Scan all experience files and rebuild index.md + _index.md for each category."""
    root = base_dir or EXPERIENCE_ROOT
    total = 0
    cat_counts = {}
    all_files = []

    for cat in CATEGORIES:
        cat_dir = root / cat
        if not cat_dir.exists():
            cat_counts[cat] = 0
            continue
        files = sorted(f for f in cat_dir.glob("*.md") if f.name != "_index.md")
        cat_counts[cat] = len(files)
        total += len(files)

        idx_lines = [f"# {cat} 经验索引", ""]
        for f in files:
            conf = _read_frontmatter_confidence(f)
            conf_str = f" (confidence={conf:.2f})" if conf is not None else ""
            idx_lines.append(f"- [{f.stem}]({f.name}){conf_str}")
        (cat_dir / "_index.md").write_text("\n".join(idx_lines), encoding="utf-8")

        for f in files:
            conf = _read_frontmatter_confidence(f) or 0.5
            title = _extract_title_from_file(f)
            all_files.append((f.stat().st_mtime, cat, f.name, conf, title))

    # Build index.md
    all_files.sort(reverse=True)
    lines = [
        "# 机械臂经验索引",
        "",
        f"总经验数: {total}",
        f"最后更新: {time.strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 分类分布",
    ]
    for cat in sorted(cat_counts.keys()):
        lines.append(f"- {cat}: {cat_counts[cat]}")
    lines.append("")
    lines.append("## 最近更新")
    if all_files:
        for mtime, cat, name, conf, title in all_files[:10]:
            display_title = title or name.replace(".md", "").replace("-", " ")
            lines.append(f"- [{cat}] {display_title} | {name} (confidence={conf:.2f})")
            fpath = root / cat / name
            file_bullets = _extract_bullets_from_file(fpath)
            for b in file_bullets:
                lines.append(f"  {b}")
    else:
        lines.append("（暂无经验）")

    (root / "index.md").write_text("\n".join(lines), encoding="utf-8")
    logger.info(
        "experience_index_rebuilt",
        total_experiences=total,
        categories=list(cat_counts.keys()),
    )


def _build_frontmatter(fm: dict) -> list[str]:
    """Build YAML frontmatter block."""
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            items = ", ".join(str(x) for x in v)
            lines.append(f"{k}: [{items}]")
        elif isinstance(v, str) and (" " in v or v == ""):
            lines.append(f'{k}: "{v}"')
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return lines
