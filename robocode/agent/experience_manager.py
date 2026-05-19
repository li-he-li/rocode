"""Experience Manager — analyzes physics data + annotations + call flow, produces experience files.

Rule-based instant layer (no LLM). Extracts patterns from collected data,
creates/updates/merges/prunes experience files in the experience filesystem.
"""

import json
import time
import difflib
from collections import defaultdict
from pathlib import Path
from robocode.services.analytics.logger import get_logger
from robocode.agent.experience_filesystem import (
    CATEGORIES,
    _read_frontmatter_confidence,
    write_experience,
    backup_before_update,
    archive_file,
    rebuild_index,
)

logger = get_logger("experience_manager")


def _top_failure_keys(failures: list[dict], top_n: int = 3) -> list[str]:
    """Extract top failure dimension values from a list of failure choices."""
    from collections import Counter

    all_values = []
    for f in failures:
        all_values.extend(f.values())
    return [v for v, _ in Counter(all_values).most_common(top_n)]


def _confidence_rationale(confidence: float, data_points: int, category: str) -> str:
    """Explain why a confidence value was assigned to an experience."""
    if confidence >= 0.8:
        return f"高置信度: 充足数据点({data_points})支撑的{category}规律"
    elif confidence >= 0.6:
        return f"中等置信度: {data_points}个数据点, 模式初步形成"
    elif confidence >= 0.4:
        return f"较低置信度: 仅{data_points}个数据点, 标记待验证"
    else:
        return f"低置信度: 数据点不足({data_points}), 不会被注入prompt"


class ExperienceManager:
    """Analyzes collected data and manages experience file lifecycle."""

    MIN_PHYSICS_DATA_POINTS = 2
    MIN_FAILURE_CASES = 1

    def __init__(self, db, session_id: str = ""):
        self._db = db
        self._session_id = session_id

    # ── Physics Analysis ──────────────────────────────────────────────

    def analyze_physics(self, min_data_points: int | None = None) -> dict | None:
        """Analyze physics data for patterns (speed vs deviation, joint limits, etc.).

        Returns dict keyed by tool_name with discovered patterns, or None if insufficient data.
        """
        threshold = min_data_points or self.MIN_PHYSICS_DATA_POINTS
        raw = self._db.get_unprocessed_physics(self._session_id) if self._db else []

        logger.info(
            "physics_analysis_start",
            total_raw_points=len(raw),
            min_required=threshold,
            session_id=self._session_id,
        )

        if len(raw) < threshold:
            logger.info("insufficient_physics_data", count=len(raw), min_required=threshold)
            return None

        by_tool = defaultdict(list)
        skipped_incomplete = 0
        for r in raw:
            before = json.loads(r["joint_angles_before"]) if r["joint_angles_before"] else None
            after = json.loads(r["joint_angles_after"]) if r["joint_angles_after"] else None
            if before is None or after is None:
                skipped_incomplete += 1
                continue
            delta = [abs(a - b) for a, b in zip(after, before)]
            by_tool[r["tool_name"]].append(
                {
                    "speed_ratio": r.get("speed_ratio", 1.0),
                    "delta": delta,
                    "max_delta": max(delta),
                    "duration_ms": r.get("duration_ms", 0),
                }
            )

        results = {}
        skipped_tools = []
        for tool_name, entries in by_tool.items():
            if len(entries) < threshold:
                skipped_tools.append({"tool": tool_name, "count": len(entries)})
                continue

            # Group by speed_ratio bands
            speed_groups = defaultdict(list)
            for e in entries:
                sr = round(e["speed_ratio"], 1)
                speed_groups[sr].append(e)

            group_stats = {}
            for sr, group in speed_groups.items():
                if len(group) < 1:
                    continue
                avg_max_delta = sum(e["max_delta"] for e in group) / len(group)
                avg_duration = sum(e["duration_ms"] for e in group) / len(group)
                group_stats[sr] = {
                    "count": len(group),
                    "avg_max_delta": round(avg_max_delta, 2),
                    "avg_duration_ms": round(avg_duration, 1),
                }

            if group_stats:
                results[tool_name] = {
                    "speed_groups": group_stats,
                    "total_data_points": len(entries),
                }

        logger.info(
            "physics_analysis_done",
            tools_analyzed=len(results),
            tools_skipped=len(skipped_tools),
            skipped_details=skipped_tools,
            skipped_incomplete=skipped_incomplete,
            patterns_found={
                t: {
                    "speed_groups": list(d["speed_groups"].keys()),
                    "data_points": d["total_data_points"],
                }
                for t, d in results.items()
            }
            if results
            else {},
        )

        return results if results else None

    # ── Annotation Processing ─────────────────────────────────────────

    def process_annotations(self) -> dict | None:
        """Process annotations: extract failure cases → tips, success → recommendations.

        Returns dict keyed by category with failures and totals.
        """
        raw = self._db.get_unprocessed_annotations(self._session_id) if self._db else []

        logger.info(
            "annotation_processing_start",
            total_annotations=len(raw),
            session_id=self._session_id,
        )

        if not raw:
            return None

        by_category = defaultdict(lambda: {"failures": [], "successes": [], "total": 0})
        for r in raw:
            cat = r["category"]
            choices = json.loads(r["choices"]) if r["choices"] else {}
            by_category[cat]["total"] += 1
            if r["is_failure"]:
                by_category[cat]["failures"].append(choices)
            else:
                by_category[cat]["successes"].append(choices)

        result = dict(by_category)

        breakdown = {
            cat: {
                "total": d["total"],
                "failures": len(d["failures"]),
                "successes": len(d["successes"]),
                "top_failure_reasons": _top_failure_keys(d["failures"]),
            }
            for cat, d in result.items()
        }
        logger.info("annotation_processing_done", categories=breakdown)

        return result

    # ── Call Flow Analysis ────────────────────────────────────────────

    def analyze_call_flow(self) -> dict | None:
        """Analyze tool call chains for common sequences, retry patterns, and
        instruction-to-tool mappings.

        Returns dict with 'sequences', 'retries', and 'instruction_map'.
        """
        calls = self._db.list_tool_calls(self._session_id) if self._db else []

        logger.info(
            "call_flow_analysis_start",
            total_calls=len(calls),
            session_id=self._session_id,
        )

        if not calls:
            return None

        # Group by task_instruction
        by_task = defaultdict(list)
        for c in calls:
            task = c.get("task_instruction") or ""
            if task:
                by_task[task].append(c)

        # Extract sequences
        sequences = []
        for task, task_calls in by_task.items():
            seq = [
                c["tool_name"] for c in sorted(task_calls, key=lambda x: x.get("turn_number", 0))
            ]
            if len(seq) >= 2:
                sequences.append({"task": task[:60], "tools": seq})

        # Detect retry patterns: same tool_name used consecutively after failure
        retries = []
        for task, task_calls in by_task.items():
            sorted_calls = sorted(task_calls, key=lambda x: x.get("turn_number", 0))
            for i in range(len(sorted_calls) - 1):
                curr = sorted_calls[i]
                next_c = sorted_calls[i + 1]
                if curr["tool_name"] != next_c["tool_name"]:
                    continue
                curr_result = json.loads(curr.get("result", "{}"))
                if not curr_result.get("success", True):
                    retries.append(
                        {
                            "task": task[:60],
                            "tool_name": curr["tool_name"],
                            "retry_count": 1,
                        }
                    )

        result: dict = {}
        if sequences:
            result["sequences"] = sequences
        if retries:
            result["retries"] = retries

        logger.info(
            "call_flow_analysis_done",
            tasks_analyzed=len(by_task),
            sequences_found=len(sequences),
            retries_found=len(retries),
            top_sequences=[
                {"task": s["task"], "chain": " → ".join(s["tools"])} for s in sequences[:5]
            ],
            retry_tools=list({r["tool_name"] for r in retries}),
        )

        return result if result else None

    # ── Experience CRUD ───────────────────────────────────────────────

    def create_experience(
        self,
        category: str,
        domain: str,
        title: str,
        data: dict | None = None,
        confidence: float = 0.5,
        data_points: int = 0,
        annotations: dict | None = None,
        call_flows: dict | None = None,
        bullets: list[str] | None = None,
    ) -> tuple[dict, str]:
        """Build frontmatter and body for an experience file.

        Returns (frontmatter_dict, body_markdown).
        """
        now = time.strftime("%Y-%m-%d")
        is_physics = category == "physics"

        frontmatter = {
            "type": "physics" if is_physics else "operational",
            "tags": [category, domain],
            "confidence": confidence,
            "data_points": data_points,
            "sources": self._session_id,
            "created": now,
            "updated": now,
        }
        if not is_physics:
            frontmatter["refs"] = ""
            frontmatter["success"] = True

        # Build body
        body_parts = [f"# {title}", ""]
        if confidence < 0.5:
            body_parts.append("[待验证] 基于有限数据点，需更多观察")
            body_parts.append("")

        body_parts.append("## 概览")
        body_parts.append("")
        body_parts.append(f"- 置信度: {confidence}")
        body_parts.append(f"- 数据点数: {data_points}")
        body_parts.append(f"- 来源会话: {self._session_id}")
        body_parts.append("")

        merged_suggestions: list[str] = []

        if is_physics and data:
            body_parts.append("## 物理规律")
            body_parts.append("")
            body_parts.extend(self._render_physics_data(data))
            body_parts.append("")
            body_parts.append("## 数据支撑")
            body_parts.append("")
            body_parts.extend(self._render_data_table(data))
            merged_suggestions.extend(self._render_physics_suggestions(data))
        else:
            if annotations:
                body_parts.append("## 案例")
                body_parts.append("")
                body_parts.extend(self._render_annotations(annotations))
                body_parts.append("")
            if call_flows:
                body_parts.append("## 推荐工具流程")
                body_parts.append("")
                body_parts.extend(self._render_call_flows(call_flows))
                merged_suggestions.extend(
                    self._render_operational_suggestions(annotations, call_flows)
                )

        if bullets:
            merged_suggestions.extend(str(b) for b in bullets)

        if merged_suggestions:
            body_parts.append("")
            body_parts.append("## 建议")
            body_parts.append("")
            body_parts.extend(merged_suggestions)

        body = "\n".join(body_parts)
        logger.info(
            "experience_created",
            type=frontmatter.get("type"),
            category=category,
            domain=domain,
            title=title,
            confidence=confidence,
            data_points=data_points,
            rationale=_confidence_rationale(confidence, data_points, category),
        )
        return frontmatter, body

    def should_prune(self, confidence: float, data_points: int) -> bool:
        """Check if an experience should be pruned."""
        return confidence < 0.3 and data_points < 5

    # ── Experience Update / Merge / Prune ─────────────────────────────

    def update_experience(
        self,
        category: str,
        filename: str,
        frontmatter_updates: dict | None = None,
        body: str | None = None,
        base_dir=None,
    ) -> bool:
        """Update an existing experience file. Backs up current version first.

        Returns True if the file existed and was updated.
        """
        from robocode.agent.experience_filesystem import (
            EXPERIENCE_ROOT,
            backup_before_update,
            write_experience,
        )

        root = base_dir or EXPERIENCE_ROOT
        filepath = root / category / filename
        if not filepath.exists():
            logger.warning("experience_update_missing", file_path=str(filepath))
            return False

        # Read existing frontmatter
        existing_fm = self._read_frontmatter(filepath)
        old_confidence = existing_fm.get("confidence", 0)

        if frontmatter_updates:
            existing_fm.update(frontmatter_updates)
        existing_fm["updated"] = time.strftime("%Y-%m-%d")

        # Use new body or keep existing
        if body is None:
            body = self._read_body(filepath)

        backup_before_update(category, filename, base_dir=root)
        write_experience(category, filename, existing_fm, body, base_dir=root)

        new_confidence = existing_fm.get("confidence", 0)
        delta = new_confidence - old_confidence
        logger.info(
            "experience_updated",
            file_path=str(filepath),
            confidence_delta=round(delta, 3),
        )
        return True

    def merge_experiences(self, base_dir=None) -> int:
        """Scan for similar experiences in same category (>80% similarity) and merge.

        Archived originals go to _archive/. Returns number of merges performed.
        """
        from robocode.agent.experience_filesystem import EXPERIENCE_ROOT

        root = base_dir or EXPERIENCE_ROOT
        # Count total candidates
        total_files = 0
        cat_file_counts = {}
        for cat in CATEGORIES:
            cat_dir = root / cat
            if not cat_dir.exists():
                continue
            files = sorted(f for f in cat_dir.glob("*.md") if f.name != "_index.md")
            if files:
                cat_file_counts[cat] = len(files)
                total_files += len(files)

        logger.info(
            "merge_scan_start",
            total_files=total_files,
            categories=cat_file_counts,
        )

        merged_count = 0
        merge_decisions = []
        for cat in CATEGORIES:
            cat_dir = root / cat
            if not cat_dir.exists():
                continue
            files = sorted(f for f in cat_dir.glob("*.md") if f.name != "_index.md")
            if len(files) < 2:
                continue

            # Find similar pairs
            merged = set()
            for i in range(len(files)):
                if files[i].name in merged:
                    continue
                for j in range(i + 1, len(files)):
                    if files[j].name in merged:
                        continue
                    sim = self._file_similarity(files[i], files[j])
                    if sim < 0.8:
                        continue

                    # Merge: higher data_points becomes target, lower becomes source
                    fm_a = self._read_frontmatter(files[i])
                    fm_b = self._read_frontmatter(files[j])
                    if fm_a.get("data_points", 0) >= fm_b.get("data_points", 0):
                        target, source = files[i], files[j]
                        target_fm, source_fm = fm_a, fm_b
                    else:
                        target, source = files[j], files[i]
                        target_fm, source_fm = fm_b, fm_a

                    # Log merge decision
                    decision = {
                        "category": cat,
                        "target": target.name,
                        "source": source.name,
                        "similarity": round(sim, 3),
                        "target_confidence": target_fm.get("confidence", 0),
                        "source_confidence": source_fm.get("confidence", 0),
                        "target_data_points": target_fm.get("data_points", 0),
                        "source_data_points": source_fm.get("data_points", 0),
                    }
                    merge_decisions.append(decision)
                    logger.info("merge_decision", **decision)

                    # Combine: average confidence, sum data_points, merge tags
                    merged_fm = {**target_fm}
                    merged_fm["confidence"] = round(
                        (target_fm.get("confidence", 0.5) + source_fm.get("confidence", 0.5)) / 2, 2
                    )
                    merged_fm["data_points"] = target_fm.get("data_points", 0) + source_fm.get(
                        "data_points", 0
                    )
                    tags = list(
                        set(
                            (
                                target_fm.get("tags", [])
                                if isinstance(target_fm.get("tags"), list)
                                else [target_fm.get("tags", cat)]
                            )
                            + (
                                source_fm.get("tags", [])
                                if isinstance(source_fm.get("tags"), list)
                                else [source_fm.get("tags", cat)]
                            )
                        )
                    )
                    merged_fm["tags"] = tags
                    merged_fm["updated"] = time.strftime("%Y-%m-%d")

                    # Merge body: append source body with attribution, deduplicate bullets
                    target_body = self._read_body(target)
                    source_body = self._read_body(source)
                    merged_body = self._merge_bodies(target_body, source_body, source.name)

                    # Archive source, update target
                    archive_file(cat, source.name, base_dir=root)
                    merged.add(source.name)
                    backup_before_update(cat, target.name, base_dir=root)
                    write_experience(cat, target.name, merged_fm, merged_body, base_dir=root)
                    merged_count += 1

            # Rebuild after merging
            if merged:
                rebuild_index(base_dir=root)

        logger.info(
            "merge_scan_done",
            merges_performed=merged_count,
            total_merge_decisions=len(merge_decisions),
        )

        return merged_count

    def prune_experiences(self, base_dir=None) -> int:
        """Archive experiences with confidence < 0.3 and data_points < 5.

        Returns number of files pruned.
        """
        from robocode.agent.experience_filesystem import EXPERIENCE_ROOT

        root = base_dir or EXPERIENCE_ROOT
        # Scan all files first
        all_files = []
        for cat in CATEGORIES:
            cat_dir = root / cat
            if not cat_dir.exists():
                continue
            for f in cat_dir.glob("*.md"):
                if f.name == "_index.md":
                    continue
                conf = _read_frontmatter_confidence(f) or 0.5
                fm = self._read_frontmatter(f)
                dp = fm.get("data_points", 0)
                all_files.append(
                    {
                        "category": cat,
                        "filename": f.name,
                        "confidence": conf,
                        "data_points": dp,
                    }
                )

        candidates = [f for f in all_files if self.should_prune(f["confidence"], f["data_points"])]

        logger.info(
            "prune_scan_start",
            total_files=len(all_files),
            candidates=len(candidates),
            candidate_details=[
                {
                    "file": f"{c['category']}/{c['filename']}",
                    "confidence": c["confidence"],
                    "data_points": c["data_points"],
                }
                for c in candidates
            ],
        )

        pruned = 0
        for c in candidates:
            cat, filename = c["category"], c["filename"]
            logger.info(
                "prune_decision",
                file=f"{cat}/{filename}",
                confidence=c["confidence"],
                data_points=c["data_points"],
                reason="confidence < 0.3 且 data_points < 5",
            )
            archive_file(cat, filename, base_dir=root)
            pruned += 1

        if pruned:
            rebuild_index(base_dir=root)
            logger.info("prune_scan_done", pruned_count=pruned)
        elif candidates:
            logger.info(
                "prune_scan_done", pruned_count=0, note="candidates found but archive failed"
            )
        # No else: nothing to prune, no log needed

        return pruned

    @staticmethod
    def _read_frontmatter(filepath: Path) -> dict:
        """Parse YAML frontmatter from a file into a dict."""
        try:
            content = filepath.read_text(encoding="utf-8")
            if not content.startswith("---"):
                return {}
            end = content.find("---", 3)
            if end == -1:
                return {}
            fm = {}
            for line in content[3:end].strip().split("\n"):
                if ":" in line:
                    key, _, val = line.partition(":")
                    val = val.strip().strip('"')
                    if val.startswith("[") and val.endswith("]"):
                        val = [v.strip() for v in val[1:-1].split(",")]
                    elif val.replace(".", "").isdigit():
                        val = float(val) if "." in val else int(val)
                    fm[key.strip()] = val
            return fm
        except Exception:
            return {}

    @staticmethod
    def _read_body(filepath: Path) -> str:
        """Read the Markdown body (after YAML frontmatter) from a file."""
        try:
            content = filepath.read_text(encoding="utf-8")
            if not content.startswith("---"):
                return content
            end = content.find("---", 3)
            if end == -1:
                return content
            return content[end + 3 :].strip()
        except Exception:
            return ""

    @staticmethod
    def extract_existing_bullets(filepath: Path) -> list[str]:
        """Extract bullets under ## 建议 from an existing experience file."""
        try:
            body = ExperienceManager._read_body(filepath)
        except Exception:
            return []
        in_section = False
        bullets: list[str] = []
        for line in body.split("\n"):
            stripped = line.strip()
            if stripped.startswith("## "):
                in_section = stripped == "## 建议"
                continue
            if in_section and stripped.startswith("- [") and "]" in stripped:
                bullets.append(stripped)
        return bullets

    @staticmethod
    def _file_similarity(f1: Path, f2: Path) -> float:
        """Compute text similarity ratio between two files' bodies."""
        try:
            b1 = ExperienceManager._read_body(f1)
            b2 = ExperienceManager._read_body(f2)
            return difflib.SequenceMatcher(None, b1, b2).ratio()
        except Exception:
            return 0.0

    @staticmethod
    def _merge_bodies(target_body: str, source_body: str, source_name: str) -> str:
        """Merge two experience bodies, deduplicating ## 建议 bullets."""
        from robocode.agent.reflector import deduplicate_bullets

        target_bullets = []
        other_target_lines = []
        in_suggestions = False
        for line in target_body.split("\n"):
            stripped = line.strip()
            if stripped.startswith("## "):
                in_suggestions = stripped == "## 建议"
                if not in_suggestions:
                    other_target_lines.append(line)
                continue
            if in_suggestions:
                if stripped.startswith("- [") and "]" in stripped:
                    target_bullets.append(stripped)
            else:
                other_target_lines.append(line)

        source_bullets = []
        other_source_lines = []
        in_suggestions = False
        for line in source_body.split("\n"):
            stripped = line.strip()
            if stripped.startswith("## "):
                in_suggestions = stripped == "## 建议"
                if not in_suggestions:
                    other_source_lines.append(line)
                continue
            if in_suggestions:
                if stripped.startswith("- [") and "]" in stripped:
                    source_bullets.append(stripped)
            else:
                other_source_lines.append(line)

        merged_bullets = deduplicate_bullets(source_bullets, target_bullets)
        all_bullets = target_bullets + merged_bullets

        parts = [other_target_lines]
        if other_source_lines:
            parts.append(["", "---", "", f"# 合并自: {source_name}", ""] + other_source_lines)
        if all_bullets:
            parts.append(["", "## 建议", ""] + all_bullets)

        return "\n".join(line for part in parts for line in part)

    # ── Rendering helpers ─────────────────────────────────────────────

    _TOOL_LABELS: dict[str, str] = {
        "move_robot_xyz": "笛卡尔空间直线移动",
        "move_robot_joints": "关节空间移动",
        "move_robot_home": "回零位",
        "move_path": "路径规划移动",
        "control_suction": "吸盘控制",
        "servo_gripper_control": "伺服夹爪控制",
        "6d_grasp": "6D 视觉抓取",
        "generate_and_run_sdk_code": "SDK 代码生成执行",
        "execute_command": "系统命令执行",
        "run_script": "脚本执行",
    }

    _CAT_LABELS: dict[str, str] = {
        "motion": "运动控制",
        "gripper": "夹爪操作",
        "grasp": "6D 抓取",
        "code": "代码执行",
        "script": "脚本执行",
        "general": "通用操作",
    }

    @classmethod
    def _tool_label(cls, tool_name: str) -> str:
        label = cls._TOOL_LABELS.get(tool_name, "")
        return f"{tool_name}（{label}）" if label else tool_name

    @staticmethod
    def _render_physics_data(data: dict) -> list[str]:
        lines = []
        for tool_name, tool_data in data.items():
            lines.append(f"### {ExperienceManager._tool_label(tool_name)}")
            sg = tool_data.get("speed_groups", {})
            for sr, stats in sorted(sg.items()):
                lines.append(
                    f"- 速度比 {sr}: 平均最大偏差={stats['avg_max_delta']}°, 样本={stats['count']}"
                )
        return lines

    @staticmethod
    def _render_data_table(data: dict) -> list[str]:
        lines = []
        for tool_name, tool_data in data.items():
            sg = tool_data.get("speed_groups", {})
            if sg:
                lines.append(f"### {ExperienceManager._tool_label(tool_name)}")
                lines.append("| speed_ratio | samples | avg_max_delta | avg_duration_ms |")
                lines.append("|------------|---------|---------------|-----------------|")
                for sr, stats in sorted(sg.items()):
                    lines.append(
                        f"| {sr} | {stats['count']} | {stats['avg_max_delta']}° | "
                        f"{stats['avg_duration_ms']:.0f}ms |"
                    )
        return lines

    @staticmethod
    def _render_physics_suggestions(data: dict) -> list[str]:
        lines = []
        for tool_name, tool_data in data.items():
            sg = tool_data.get("speed_groups", {})
            if not sg:
                continue
            high_speed_groups = {sr: s for sr, s in sg.items() if sr >= 0.6}
            low_speed_groups = {sr: s for sr, s in sg.items() if sr < 0.6}
            if high_speed_groups and low_speed_groups:
                high_avg = sum(s["avg_max_delta"] for s in high_speed_groups.values()) / len(
                    high_speed_groups
                )
                low_avg = sum(s["avg_max_delta"] for s in low_speed_groups.values()) / len(
                    low_speed_groups
                )
                if high_avg > low_avg * 1.5:
                    lines.append(
                        f"- {tool_name}: 高速(speed≥0.6)偏差比低速大 {high_avg / low_avg:.1f}x，建议使用 speed_ratio≤0.5"
                    )
        if not lines:
            lines.append("- 数据量不足，暂无明确建议")
        return lines

    @staticmethod
    def _render_annotations(data: dict) -> list[str]:
        lines = []
        for cat, cat_data in data.items():
            label = ExperienceManager._CAT_LABELS.get(cat, cat)
            lines.append(f"### {cat}（{label}）")
            lines.append(f"- 总数: {cat_data['total']}")
            failures = cat_data.get("failures", [])
            successes = cat_data.get("successes", [])
            if successes:
                lines.append(f"- 成功: {len(successes)} 例")
            if failures:
                lines.append(f"- 失败: {len(failures)} 例")
                for f in failures[:3]:
                    details = ", ".join(f"{k}={v}" for k, v in f.items())
                    lines.append(f"  - {details}")
        return lines

    @staticmethod
    def _render_call_flows(data: dict) -> list[str]:
        lines = []
        seqs = data.get("sequences", [])
        if seqs:
            for s in seqs[:5]:
                tool_chain = " → ".join(s["tools"])
                lines.append(f"- `{tool_chain}` ({s['task']})")
        return lines

    @staticmethod
    def _render_operational_suggestions(
        annotations: dict | None, call_flows: dict | None
    ) -> list[str]:
        lines = []
        if annotations:
            for cat, cat_data in annotations.items():
                if cat_data.get("failures"):
                    lines.append(
                        f"- [{cat}] 发现 {len(cat_data['failures'])} 例失败，建议查阅失败详情"
                    )
                if cat_data.get("successes"):
                    lines.append(f"- [{cat}] {len(cat_data['successes'])} 例成功操作可参考")
        if call_flows and call_flows.get("sequences"):
            lines.append("- 推荐按上述工具流程执行同类任务")
        if not lines:
            lines.append("- 数据积累中，暂无建议")
        return lines
