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
        self.total_experiences = 0
        self._load_index()

    # ── public API ────────────────────────────────────────────────────

    def has_experiences(self) -> bool:
        return self.total_experiences > 0

    def get_visible_experiences(self, min_confidence: float | None = None) -> list[dict]:
        threshold = min_confidence if min_confidence is not None else _CONFIDENCE_MIN
        filtered = [e for e in self._entries if e.get("confidence", 0) >= threshold]
        filtered.sort(key=lambda e: e.get("confidence", 0), reverse=True)
        return filtered

    def get_index_summary(self) -> str:
        visible = self.get_visible_experiences()
        if not visible:
            return ""

        lines = [
            "## 经验知识库（强制查阅）",
            "",
            "在执行任何运动、抓取、夹爪操作前，你必须：",
            "1. 查看下方索引，找到与当前任务相关的经验",
            "2. 使用 read_file 工具读取相关经验文件全文",
            "3. 将经验中的建议纳入你的执行计划",
            "",
            "忽略此指令导致的操作失败，责任在你。",
            "",
            "### 经验索引:",
        ]
        for e in visible[:10]:
            marker = "⭐" if e.get("confidence", 0) >= _CONFIDENCE_STAR else "⚠"
            lines.append(
                f"- {marker} [{e.get('category', '?')}] {e.get('title', e.get('filename', '?'))} "
                f"(confidence={e.get('confidence', 0):.2f}) → {e.get('category', '')}/{e.get('filename', '')}"
            )
            for b in e.get("bullets", []):
                lines.append(f"  {b}")
        return "\n".join(lines)

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

        _ENTRY_RE = re.compile(
            r"-\s*\[(\w+)\]\s+(.+?)\s*\|\s*([\w./-]+\.md)\s*\(confidence=([\d.]+)\)"
        )
        _ENTRY_OLD_RE = re.compile(r"-\s*\[(\w+)\]\s+([\w./-]+\.md)(?:\s+\(confidence=([\d.]+)\))?")
        lines = content.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            em = _ENTRY_RE.match(line)
            if em:
                cat, title, filename, conf_str = (
                    em.group(1),
                    em.group(2).strip(),
                    em.group(3),
                    em.group(4),
                )
                try:
                    conf = float(conf_str)
                except (ValueError, TypeError):
                    conf = 0.5
            else:
                em_old = _ENTRY_OLD_RE.match(line)
                if not em_old:
                    i += 1
                    continue
                cat = em_old.group(1)
                filename = em_old.group(2)
                conf = 0.5
                if em_old.group(3):
                    try:
                        conf = float(em_old.group(3))
                    except (ValueError, TypeError):
                        pass
                title = filename.replace(".md", "").replace("-", " ")

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
                    "filename": filename,
                    "title": title,
                    "confidence": conf,
                    "bullets": bullets,
                }
            )
            i = j
