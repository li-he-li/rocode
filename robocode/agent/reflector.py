"""Reflector — LLM-based post-session reflection on structured analysis summaries.

Runs AFTER rule-based ExperienceManager analysis. Consumes the structured
summary (not raw data), produces delta bullets that capture cross-dimensional
causal patterns the rule layer cannot detect.
"""

import difflib
from robocode.services.analytics.logger import get_logger

logger = get_logger("reflector")

REFLECTOR_SYSTEM_PROMPT = """你是机械臂操作分析专家。你将收到本轮会话的结构化数据摘要，
请从中提炼 3-8 条经验洞察（delta bullets）。

要求：
1. 每条 <60 字，聚焦可操作建议
2. 优先关注：跨维度关联（如"速度+振动+精度"的联合关系）、失败根因推理、参数修正路径
3. 不要复述数据，要给出因果推断和行动建议
4. 不确定时标注 [待验证]
5. 输出格式：每条一行，"- [类型] 内容"，类型为 L0/L1/L2/PARAM/PATTERN/CAUTION

示例：
- [L2] move_robot_xyz z<50 且 x>350 时 IK 无解，改为 z≥80 后成功
- [PARAM] speed_ratio 0.3~0.5 是运动精度的甜蜜点，>0.6 振动显著
- [CAUTION] servo_gripper angle<10 无实际抓取力，首次失败后调至 25 成功
- [PATTERN] 抓取任务的标准流程：get_status → move_xyz → gripper → 验证"""


def _build_reflection_context(
    physics: dict | None,
    annotations: dict | None,
    call_flows: dict | None,
) -> str:
    parts: list[str] = []

    if physics:
        parts.append("## 物理数据分析")
        parts.append("")
        for tool, data in physics.items():
            for sr, stats in data.get("speed_groups", {}).items():
                parts.append(
                    f"- {tool} speed={sr}: "
                    f"avg_max_delta={stats['avg_max_delta']}°, "
                    f"samples={stats['count']}, "
                    f"avg_duration={stats['avg_duration_ms']}ms"
                )

    if annotations:
        parts.append("")
        parts.append("## 人工标注")
        parts.append("")
        for cat, d in annotations.items():
            top_reasons = d.get("top_failure_reasons", [])
            parts.append(
                f"- [{cat}] total={d['total']}, "
                f"failures={len(d.get('failures', []))}, "
                f"top_reasons={top_reasons}"
            )
            for f in d.get("failures", [])[:3]:
                details = ", ".join(f"{k}={v}" for k, v in f.items())
                parts.append(f"  失败详情: {details}")

    if call_flows:
        seqs = call_flows.get("sequences", [])
        retries = call_flows.get("retries", [])
        if seqs:
            parts.append("")
            parts.append("## 工具调用序列")
            parts.append("")
            for s in seqs:
                parts.append(f"- {' → '.join(s['tools'])} ({s['task']})")
        if retries:
            parts.append("")
            parts.append("## 重试模式")
            parts.append("")
            for r in retries:
                parts.append(f"- {r['tool_name']} 失败后重试 (task: {r['task']})")

    return "\n".join(parts)


def _extract_bullets(text: str) -> list[str]:
    bullets: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        # Standard: - [TYPE] content
        if stripped.startswith("- [") and "]" in stripped:
            bullets.append(stripped)
        # Numbered: 1. [TYPE] content  or  1. **TYPE** content
        elif len(stripped) > 3 and stripped[0].isdigit() and stripped[1] in ".":
            rest = stripped[2:].strip()
            if rest.startswith("[") and "]" in rest:
                bullets.append(f"- {rest}")
            elif rest.startswith("**") and "**" in rest[2:]:
                end = rest.index("**", 2)
                tag = rest[2:end]
                content = rest[end + 2 :].strip()
                if content:
                    bullets.append(f"- [{tag}] {content}")
        # Bold: - **TYPE** content
        elif stripped.startswith("- **") and "**" in stripped[4:]:
            end = stripped.index("**", 4)
            tag = stripped[4:end]
            content = stripped[end + 2 :].strip()
            if content:
                bullets.append(f"- [{tag}] {content}")
        # Reversed: [TYPE] - content
        elif stripped.startswith("[") and "] - " in stripped:
            bracket_end = stripped.index("]")
            tag = stripped[1:bracket_end]
            content = stripped[bracket_end + 1 :].strip().lstrip("-").strip()
            if content:
                bullets.append(f"- [{tag}] {content}")

    if not bullets and text.strip():
        bullets.append(f"- [REFLECT] {text.strip()[:120]}")

    return bullets


def deduplicate_bullets(
    new_bullets: list[str],
    existing_bullets: list[str],
    threshold: float = 0.75,
) -> list[str]:
    kept: list[str] = []
    for b in new_bullets:
        if not any(
            difflib.SequenceMatcher(None, b, eb).ratio() > threshold for eb in existing_bullets
        ):
            kept.append(b)
    return kept


class Reflector:
    """One-shot LLM reflection on structured analysis summaries."""

    def __init__(self, provider, max_bullets: int = 8):
        self._provider = provider
        self._max_bullets = max_bullets

    async def reflect(
        self,
        physics: dict | None = None,
        annotations: dict | None = None,
        call_flows: dict | None = None,
    ) -> list[str]:
        context = _build_reflection_context(physics, annotations, call_flows)
        if not context.strip():
            logger.info("reflector_skip", reason="empty_context")
            return []

        logger.info("reflector_start", context_chars=len(context))

        full_text = ""
        async for event in self._provider.stream(
            system=REFLECTOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": context}],
            tools=[],
        ):
            if event.kind == "text_delta":
                full_text += event.payload.get("delta", "")

        bullets = _extract_bullets(full_text)[: self._max_bullets]

        logger.info(
            "reflector_done",
            raw_chars=len(full_text),
            bullets_produced=len(bullets),
            bullets=bullets,
        )
        return bullets
