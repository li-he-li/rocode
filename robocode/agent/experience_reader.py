"""Experience Reader — loads experience index at startup, provides summary for SYSTEM_PROMPT.

Reads robocode/experience/index.md at initialization, parses entries,
filters by confidence threshold, and generates the mandatory lookup block.
"""

import re
from pathlib import Path
from robocode.services.analytics.logger import get_logger

logger = get_logger("experience_reader")

EXPERIENCE_ROOT = Path(__file__).resolve().parent.parent / "experience"

_CONFIDENCE_STAR = 0.7  # >= this → ⭐
_CONFIDENCE_MIN = 0.4  # < this → hidden from summary


class ExperienceReader:
    def __init__(self, base_dir: Path | None = None):
        self._base = base_dir or EXPERIENCE_ROOT
        self._entries: list[dict] = []
        self._tool_tips: dict[str, list[str]] = {}
        self.total_experiences = 0
        self._load_index()
        self._build_tool_index()

    # ── public API ────────────────────────────────────────────────────

    def has_experiences(self) -> bool:
        return self.total_experiences > 0

    def reload(self):
        """重新加载 index 和工具索引（经验文件变更后调用）。"""
        self._entries = []
        self._tool_tips = {}
        self._load_index()
        self._build_tool_index()

    def get_visible_experiences(self, min_confidence: float | None = None) -> list[dict]:
        threshold = min_confidence if min_confidence is not None else _CONFIDENCE_MIN
        filtered = [e for e in self._entries if e.get("confidence", 0) >= threshold]
        filtered.sort(key=lambda e: e.get("confidence", 0), reverse=True)
        return filtered

    def get_index_summary(self) -> str:
        """生成经验目录，供 LLM 按需查阅。只给标题+摘要，不放全文 bullet。"""
        visible = self.get_visible_experiences()
        if not visible:
            return ""

        lines = [
            "## 经验目录（用 read_file 按需查阅）",
            "",
            "| # | 经验 | 置信度 | 文件路径 |",
            "|---|------|:------:|----------|",
        ]
        for i, e in enumerate(visible, 1):
            marker = "⭐" if e.get("confidence", 0) >= _CONFIDENCE_STAR else "⚠"
            title = e.get("title", e.get("filename", "?"))
            conf = e.get("confidence", 0)
            rel_path = e.get("rel_path", e.get("filename", "?"))
            abstract = e.get("description", "")
            # fallback: 取第一条 bullet 前 50 字
            if not abstract:
                bullets = e.get("bullets", [])
                if bullets:
                    b = bullets[0]
                    if "]" in b:
                        abstract = b.split("]", 1)[1].strip()[:50]
                    else:
                        abstract = b[:50]
            lines.append(f"| {i} | {marker} **{title}** — {abstract} | {conf:.2f} | {rel_path} |")

        lines.append("")
        lines.append(
            "> **使用方式**：先看目录找到相关的经验，然后用 `read_file` "
            "工具读取经验文件全文。执行任何运动/抓取/夹爪操作前，必须查阅相关经验。"
        )
        return "\n".join(lines)

    def get_tool_tips(self, tool_name: str, max_tips: int = 3) -> list[str]:
        """返回与该工具关联的经验提醒（最多 max_tips 条）。"""
        tips = self._tool_tips.get(tool_name, [])
        return tips[:max_tips]

    def _build_tool_index(self):
        """从所有经验文件的 bullet 中提取 @tool_name，构建反向索引。"""
        self._tool_tips = {}
        for entry in self._entries:
            file_bullets = self._read_file_bullets(entry["rel_path"])
            for bullet in file_bullets:
                tools = re.findall(r"@(\w+)", bullet)
                if not tools:
                    continue
                clean = re.sub(r"\s*@\w+", "", bullet).strip()
                for tool_name in tools:
                    self._tool_tips.setdefault(tool_name, []).append(clean)

    def _read_file_bullets(self, rel_path: str) -> list[str]:
        """从经验文件的 ## 建议 section 提取全部 bullet。"""
        filepath = self._base / rel_path
        if not filepath.exists():
            return []
        try:
            content = filepath.read_text(encoding="utf-8")
        except Exception:
            return []

        # 跳过 YAML frontmatter
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                content = content[end + 3 :]

        bullets: list[str] = []
        in_section = False
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("## "):
                in_section = stripped == "## 建议"
                continue
            if in_section and stripped.startswith("- [") and "]" in stripped:
                bullets.append(stripped)
        return bullets

    # ── internal ──────────────────────────────────────────────────────

    def _load_index(self):
        idx_path = self._base / "index.md"
        if not idx_path.exists():
            logger.info("experience_index_not_found", path=str(idx_path))
            return

        try:
            content = idx_path.read_text(encoding="utf-8")
            self._parse_index(content)
            visible_count = len(self.get_visible_experiences())
            logger.info(
                "experience_index_loaded",
                total_experiences=self.total_experiences,
                visible_count=visible_count,
                categories=list(set(e.get("category", "") for e in self._entries)),
            )
        except Exception:
            logger.exception("experience_index_parse_failed")

    def _parse_index(self, content: str):
        m = re.search(r"总经验数:\s*(\d+)", content)
        if m:
            self.total_experiences = int(m.group(1))

        lines = content.split("\n")

        # Try markdown table format: | N | ⭐ **title** — desc | conf | path |
        # Extract description between **title** and | conf |
        _TABLE_RE = re.compile(
            r"\|\s*\d+\s*\|[^|]*\*\*(.+?)\*\*\s*—?\s*(.*?)\s*\|\s*([\d.]+)\s*\|\s*([\w./-]+\.md)\s*\|"
        )
        for line in lines:
            tm = _TABLE_RE.match(line.strip())
            if not tm:
                continue
            title = tm.group(1).strip()
            desc = tm.group(2).strip().rstrip("|").strip()
            conf_str = tm.group(3)
            rel_path = tm.group(4)
            try:
                conf = float(conf_str)
            except (ValueError, TypeError):
                conf = 0.5
            cat, fname = (rel_path.split("/", 1) + ["general"])[:2]
            if "/" not in rel_path:
                cat, fname = "general", rel_path
            self._entries.append(
                {
                    "category": cat,
                    "filename": fname,
                    "rel_path": rel_path,
                    "title": title,
                    "confidence": conf,
                    "bullets": [],
                    "description": desc,
                }
            )

        if self._entries:
            return

        # Fallback: old format - title | category/filename.md (confidence=X)
        _ENTRY_RE = re.compile(r"-\s+(.+?)\s*\|\s*([\w./-]+\.md)\s*\(confidence=([\d.]+)\)")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            em = _ENTRY_RE.match(line)
            if not em:
                i += 1
                continue
            title = em.group(1).strip()
            rel_path = em.group(2)
            conf_str = em.group(3)
            try:
                conf = float(conf_str)
            except (ValueError, TypeError):
                conf = 0.5
            cat, fname = (rel_path.split("/", 1) + ["general"])[:2]
            if "/" not in rel_path:
                cat, fname = "general", rel_path
            bullets: list[str] = []
            j = i + 1
            while j < len(lines):
                raw = lines[j]
                sub = raw.strip()
                if not sub:
                    break
                if not raw.startswith(" "):
                    break
                if sub.startswith("- [") and "]" in sub:
                    bullets.append(sub)
                    j += 1
                else:
                    break
            self._entries.append(
                {
                    "category": cat,
                    "filename": fname,
                    "rel_path": rel_path,
                    "title": title,
                    "confidence": conf,
                    "bullets": bullets,
                }
            )
            i = j
