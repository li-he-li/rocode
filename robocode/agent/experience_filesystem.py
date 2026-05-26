"""Experience filesystem — write, backup, archive, and index experience files.

Structure: experience/<category>/<filename>.md
Category is derived from filename prefix (e.g. "code-experience.md" → "code/")
or explicitly passed.
"""

import re
import time
import shutil
from pathlib import Path
from robocode.services.analytics.logger import get_logger

logger = get_logger("experience_filesystem")

EXPERIENCE_ROOT = Path(__file__).resolve().parent.parent / "experience"

# Known categories — used for rebuild_index scanning
CATEGORIES = [
    "physics",
    "code",
    "vlm",
    "motion",
    "gripper",
    "grasp",
    "hardware",
    "session",
    "general",
]


def _validate_path(category: str, filename: str) -> None:
    """Reject path traversal in category/filename."""
    for name in (category, filename):
        if not name:
            raise ValueError("must not be empty")
        if ".." in name or "/" in name or "\\" in name:
            raise ValueError(f"Invalid path component: {name!r}")


def _category_from_filename(filename: str) -> str:
    """Infer category from filename prefix before first '-'."""
    if "-" in filename:
        return filename.split("-")[0]
    return "general"


def _resolve_path(category: str, filename: str, base_dir: Path | None = None) -> Path:
    """Resolve full path for an experience file."""
    root = base_dir or EXPERIENCE_ROOT
    return root / category / filename


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


def _extract_description(filepath: Path) -> str:
    """Extract description from frontmatter or derive from file content."""
    try:
        content = filepath.read_text(encoding="utf-8")
        # Try frontmatter description field first
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                fm_text = content[3:end]
                m = re.search(r"^description:\s*(.+)$", fm_text, re.MULTILINE)
                if m:
                    return m.group(1).strip().strip('"')
        # Fallback: extract tags and bullet count to build description
        tags = []
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                fm_text = content[3:end]
                m = re.search(r"^tags:\s*\[(.+?)\]", fm_text, re.MULTILINE)
                if m:
                    tags = [t.strip() for t in m.group(1).split(",")]
        bullet_count = 0
        body = content[content.find("---", 3) + 3 :] if content.startswith("---") else content
        in_section = False
        for line in body.split("\n"):
            stripped = line.strip()
            if stripped.startswith("## "):
                in_section = stripped == "## 建议"
                continue
            if in_section and stripped.startswith("- [") and "]" in stripped:
                bullet_count += 1
        tag_str = "、".join(tags[:3]) if tags else ""
        if tag_str and bullet_count:
            return f"{tag_str}相关，{bullet_count} 条规则"
        elif bullet_count:
            return f"{bullet_count} 条操作规则"
        return ""
    except Exception:
        return ""


def _extract_tags(filepath: Path) -> list[str]:
    """Extract tags from frontmatter."""
    try:
        content = filepath.read_text(encoding="utf-8")[:2000]
        m = re.search(r"^tags:\s*\[(.+?)\]", content, re.MULTILINE)
        if m:
            return [t.strip() for t in m.group(1).split(",") if t.strip()]
    except Exception:
        pass
    return []


def write_experience(
    category: str,
    filename: str,
    frontmatter: dict,
    body: str,
    base_dir: Path | None = None,
) -> Path:
    """Write an experience file to category/filename.

    If file already exists, call backup_before_update() first.
    Returns the written file path.
    """
    _validate_path(category, filename)
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
    _validate_path(category, filename)
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
    _validate_path(category, filename)
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
    """Scan all category subdirectories and rebuild index.md in catalog format."""
    root = base_dir or EXPERIENCE_ROOT
    all_files = []

    for cat in CATEGORIES:
        cat_dir = root / cat
        if not cat_dir.exists():
            continue
        for f in sorted(cat_dir.glob("*.md")):
            conf = _read_frontmatter_confidence(f) or 0.5
            title = _extract_title_from_file(f) or f.stem.replace("-", " ")
            description = _extract_description(f)
            rel_path = f"{cat}/{f.name}"
            all_files.append((conf, cat, f.name, title, description, rel_path, f))

    total = len(all_files)
    # Sort by confidence descending
    all_files.sort(key=lambda x: (-x[0], x[1], x[3]))

    lines = [
        "# 机械臂经验目录",
        "",
        f"总经验数: {total}",
        f"最后更新: {time.strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 目录",
        "",
        "| # | 经验 | 置信度 | 文件路径 |",
        "|---|------|:------:|----------|",
    ]

    # Collect tags for topic index
    topic_map: dict[str, list[str]] = {}

    for i, (conf, cat, fname, title, desc, rel_path, fpath) in enumerate(all_files, 1):
        marker = "⭐" if conf >= 0.7 else "⚠"
        desc_text = f" — {desc}" if desc else ""
        lines.append(f"| {i} | {marker} **{title}**{desc_text} | {conf:.2f} | {rel_path} |")

        # Collect tags → file mapping for topic index
        tags = _extract_tags(fpath)
        for tag in tags:
            short = title[:30] + ("..." if len(title) > 30 else "")
            topic_map.setdefault(tag, []).append(short)

    lines.append("")
    lines.append(
        "> **使用方式**：先看目录找到相关的经验，然后用 `read_file` "
        "工具读取经验文件全文。执行任何运动/抓取/夹爪操作前，必须查阅相关经验。"
    )

    # Topic index
    if topic_map:
        lines.append("")
        lines.append("## 按主题索引")
        lines.append("")
        lines.append("| 主题 | 相关经验 |")
        lines.append("|------|---------|")
        for tag in sorted(topic_map.keys()):
            files = "、".join(topic_map[tag])
            lines.append(f"| **{tag}** | {files} |")

    (root / "index.md").write_text("\n".join(lines), encoding="utf-8")
    logger.info("experience_index_rebuilt", total_experiences=total)


def _build_frontmatter(fm: dict) -> list[str]:
    """Build YAML frontmatter block. Handles lists, strings with spaces, None."""
    lines = ["---"]
    for k, v in fm.items():
        if v is None:
            lines.append(f'{k}: ""')
        elif isinstance(v, list):
            items = ", ".join(str(x) for x in v)
            lines.append(f"{k}: [{items}]")
        elif isinstance(v, str) and (" " in v or v == ""):
            lines.append(f'{k}: "{v}"')
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return lines
