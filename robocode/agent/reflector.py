"""Reflector — LLM-based post-session reflection on structured analysis summaries.

Runs AFTER rule-based ExperienceManager analysis. Consumes the structured
summary (not raw data), produces delta bullets that capture cross-dimensional
causal patterns the rule layer cannot detect.
"""

import difflib
from robocode.services.analytics.logger import get_logger

logger = get_logger("reflector")

REFLECTOR_SYSTEM_PROMPT = """你是机械臂操作分析专家。从会话记录和用户反馈中提炼可复用的操作经验。

## 机械臂关节物理含义（推理因果规律的骨架）

| 关节 | 物理作用 | 连杆长 | 对摄像头朝向的影响 |
|------|---------|:-----:|------------------|
| J1 | 底座旋转（绕Z，轴高0mm） | — | 决定整个机械臂面朝哪个水平方向 |
| J2 | 大臂俯仰（肩，轴高166mm） | 200mm | 大臂抬起/放下，决定末端高度 |
| J3 | 小臂俯仰（肘） | — | 小臂收展，配合J2控制前后/高低 |
| J4 | 手腕旋转（绕臂轴） | — | **决定左右扫视平面**——J4变，摄像头水平方向就变 |
| J5 | 手腕俯仰（绕腕轴） | 192mm | **在J4确定的平面内上下摆**——J5变，摄像头高低角就变 |
| J6 | 末端自旋（法兰距J5=55mm） | 55mm | 微调摄像头旋转角 |

**关键因果链**：J1+J4 决定水平方向（左/右/前/后），J2+J3+J5 决定高度和俯仰（上/下/平），末端RX/RY/RZ是这些关节的合力结果。
**臂展**：J2→J3 连杆 200mm, J4→J5 连杆 192mm, J5→末端 55mm, 全伸直约 447mm。Home 位姿末端 xyz=[260, 0, 200]mm。

## 你的任务

1. 分析本次会话的数据，提炼有价值的经验
2. 对照已有经验索引，判断每条新经验应该：
   - **新增**：已有索引中没有相关内容
   - **更新**：已有索引中有相关内容，但本次发现了更准确/更完整的版本（替换旧内容）
   - **跳过**：已有索引中已有完全相同或更好的版本
3. 只输出新增和更新的内容，跳过已有的

## 核心原则

1. **用户反馈是最高优先级的信号源**——它告诉你什么该固化、什么该避免
2. **提炼因果规律，不要复述事实**——"J2/J3增大时J5必须减小才能保持朝下" 是规律，"J5=196.76" 是死值
3. **区分成功和失败**——成功时固化参数和流程，失败时记录错误路径和修正方法
4. **质量 > 数量**——宁可只输出 1 条有价值的，也不输出 5 条空洞的
5. **可操作 > 抽象**——包含具体工具名、参数值、动作序列，不要纯道理

## 输出格式

每条一行，格式：`- [意图] 内容`

- **意图**：用 2-8 个字概括这条经验的用途，自由定义
- **内容**：可直接被下次 Agent 引用的操作性建议，越具体越好

如果要更新已有经验，内容末尾追加 `→ 更新:experience/文件名.md`

## 格式示例(效果好的话允许描述物理关系)

### 运动控制
- [保持朝下] J2/J3增大（抬臂）→ J5必须减小（手腕下压）才能保持摄像头朝下，反之亦然
- [Z轴平移] move_robot_xyz 会重置 rotation 默认值 (180,0,90)，不能用它"只改z保持朝下"，用 move_robot_joints 代替
- [朝下看范围] 已验证关节范围：J2∈[120,121], J3∈[59,103], J5∈[145,197], J1≈180
- [速度选择] speed_ratio 0.3~0.5 精度最佳，≥0.6 振动显著

### VLM 桌面检测
- [VLM检测流程] search_code 找 grasp_lib → generate_and_run_sdk_code 生成脚本 → execute_command 写到 /tmp → env DASHSCOPE_API_KEY=xxx conda run -n episode python3 执行
- [API Key] DASHSCOPE_API_KEY 在 /home/li/work/Robot/.env，用 read_file 读取；用户提供的 key 优先于 .env 中的
- [写脚本到 /tmp] generate_and_run_sdk_code 允许 Path.write_text()，禁止 os/subprocess；execute_command 禁止 | > < 等 shell 元字符

### 夹爪操作
- [吸盘] control_suction(on) 后等待 0.5s 再移动，否则物体可能掉落
- [伺服夹爪] angle<10 无实际抓取力，推荐 20~90；抓取前先确认目标位置

### 代码执行
- [conda 环境] RealSense/VLM 相关脚本必须用 conda run -n episode python3 执行，Agent 本身的 .venv 没有这些依赖
- [环境变量] 传环境变量给子进程用 `env KEY=value conda run ...`，直接 `KEY=value cmd` 会被当作未知命令

## 禁止

- 不要输出任何 `- [...]` 格式以外的内容（不要标题、不要解释、不要前缀文本）
- 不要记录瞬时死值（如"J5=196.76"），要记录规律和范围
- 不要复述会话记录，要提炼抽象后的经验
- 不要输出已有索引中已有的内容（除非你要更新它）"""


def _build_reflection_context(
    transcript: list[dict],
    physics: dict | None,
    annotations: dict | None,
    call_flows: dict | None = None,
    conv_analysis: dict | None = None,
    experience_index: str | None = None,
) -> str:
    parts: list[str] = []

    # ── User feedback (highest priority) ──
    all_feedback: list[str] = []
    if annotations:
        for cat_data in annotations.values():
            for ft in cat_data.get("free_texts", []):
                if ft and ft not in all_feedback:
                    all_feedback.append(ft)

    if all_feedback:
        parts.append("## 用户反馈（最高优先级）")
        for fb in all_feedback:
            parts.append(f"用户反馈：{fb[:800]}")
        parts.append("")

    # ── Reference frame ──
    parts.append("## 参考基准（Home 零位 + 已验证范围）")
    parts.append("")
    parts.append("Home 关节角: [180, 90, 83, 30, 110, 30]° → 末端朝前方,摄像头朝前")
    parts.append("摄像头朝下已验证范围: J1≈180, J2∈[105,120], J3∈[70,85], J5∈[145,197]")
    parts.append("J4 扫视: 30°=前, 120°=左, 210°=右")
    parts.append("末端 RX≈±180°→摄像头倒转(朝下), RX≈-110°→朝前, RX≈-90°→朝侧方")
    parts.append("")

    # ── Dialogue transcript ──
    parts.append("## 会话记录")
    parts.append("")
    for msg in transcript:
        role = msg.get("role", "")
        if role == "user":
            parts.append(f"用户：{msg.get('content', '')[:500]}")
        elif role == "assistant":
            text = msg.get("content", "")
            if text and text.strip():
                parts.append(f"Agent：{text[:300]}")
        elif role == "tool_call":
            parts.append(f"Agent 调用 {msg.get('tool', '?')}：{msg.get('params', '')[:200]}")
        elif role == "tool_result":
            ok = msg.get("success", True)
            short = msg.get("message", "")[:300]
            marker = "✅" if ok else "❌"
            parts.append(f"  → {marker} {short}" if short else f"  → {marker}")
    parts.append("")

    # ── Physics summary ──
    if physics:
        parts.append("## 关节角度变化")
        for tool, data in physics.items():
            for sr, stats in data.get("speed_groups", {}).items():
                for s in stats.get("samples", [])[:3]:
                    before = s.get("before", [])
                    after = s.get("after", [])
                    delta = [round(a - b, 1) for a, b in zip(after, before)]
                    parts.append(f"- {tool} speed={sr}: delta={delta}")
        parts.append("")

    # ── Existing experience index (for dedup) ──
    if experience_index:
        parts.append("## 已有经验索引（不要重复已有内容；如需更新，末尾加 → 更新:文件名.md）")
        parts.append(experience_index)
        parts.append("")

    if not parts:
        return ""

    # Only add prompt if there's actual content to reflect on
    has_content = any(
        line.startswith("用户：") or line.startswith("Agent") or line.startswith("- ")
        for line in "\n".join(parts).split("\n")
    )
    if not has_content:
        return ""

    parts.append(
        "请以用户反馈为最高优先级，综合以上数据提炼经验。只输出 `- [意图] 内容` 格式，其余不要。"
    )
    return "\n".join(parts)


def _normalize_tag(raw_tag: str) -> str:
    """Normalize tag, stripping surrounding brackets from double-bracket cases."""
    return raw_tag.strip().strip("[]")


def _parse_bullet(line: str) -> dict | None:
    """Parse a bullet line into structured data.

    Returns dict with keys: intent, content, update_target (optional).
    Format: - [intent] content [→ 更新:path.md]
    """
    if not line.startswith("- [") or "]" not in line[3:]:
        return None

    bracket_end = line.index("]", 3)
    raw_tag = line[3:bracket_end]
    content = line[bracket_end + 1 :].strip()
    tag = _normalize_tag(raw_tag)

    if not content:
        return None

    # Check for update target: → 更新:xxx.md
    update_target = None
    if "→ 更新:" in content:
        parts = content.split("→ 更新:", 1)
        content = parts[0].strip()
        update_target = parts[1].strip()

    return {
        "intent": tag,
        "content": content,
        "update_target": update_target,
        "raw": f"- [{tag}] {content}",
    }


def _extract_bullets(text: str) -> list[str]:
    """Extract bullets from LLM output, handling various formatting styles."""
    bullets: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        # Try structured parse first
        parsed = _parse_bullet(stripped)
        if parsed:
            bullets.append(parsed["raw"])
            continue

        # Pattern: 1. [tag] content
        if len(stripped) > 3 and stripped[0].isdigit() and stripped[1] in ".":
            rest = stripped[2:].strip()
            if rest.startswith("[") and "]" in rest:
                bracket_end = rest.index("]", 1)
                raw_tag = rest[1:bracket_end]
                content = rest[bracket_end + 1 :].strip()
                tag = _normalize_tag(raw_tag)
                if content:
                    bullets.append(f"- [{tag}] {content}")
                continue

        # Pattern: - **tag** content
        if stripped.startswith("- **") and "**" in stripped[4:]:
            end = stripped.index("**", 4)
            tag = stripped[4:end]
            content = stripped[end + 2 :].strip()
            if content:
                bullets.append(f"- [{_normalize_tag(tag)}] {content}")
            continue

        # Pattern: [tag] content
        if stripped.startswith("[") and "]" in stripped:
            bracket_end = stripped.index("]")
            raw_tag = stripped[1:bracket_end]
            content = stripped[bracket_end + 1 :].strip().lstrip("-").strip()
            if content:
                bullets.append(f"- [{_normalize_tag(raw_tag)}] {content}")
            continue

        # Pattern: → [tag] content
        if "→" in stripped:
            after_arrow = stripped[stripped.index("→") + 1 :].strip()
            if after_arrow.startswith("[") and "]" in after_arrow:
                bracket_end = after_arrow.index("]")
                raw_tag = after_arrow[1:bracket_end]
                content = after_arrow[bracket_end + 1 :].strip()
                if content:
                    bullets.append(f"- [{_normalize_tag(raw_tag)}] {content}")
                continue

    if not bullets and text.strip():
        bullets.append(f"- [REFLECT] {text.strip()[:120]}")

    return bullets


def extract_bullets_with_targets(text: str) -> list[dict]:
    """Extract bullets with update targets parsed.

    Returns list of dicts: {intent, content, update_target, raw}
    """
    results = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        parsed = _parse_bullet(stripped)
        if parsed:
            results.append(parsed)
    return results


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

    def __init__(self, provider, max_bullets: int = 10):
        self._provider = provider
        self._max_bullets = max_bullets

    async def reflect(
        self,
        transcript: list[dict] | None = None,
        physics: dict | None = None,
        annotations: dict | None = None,
        call_flows: dict | None = None,
        conv_analysis: dict | None = None,
        experience_index: str | None = None,
    ) -> list[dict]:
        """Run LLM reflection. Returns list of dicts with keys:
        {intent, content, update_target, raw}
        """
        context = _build_reflection_context(
            transcript or [], physics, annotations, call_flows, conv_analysis, experience_index
        )
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

        parsed = extract_bullets_with_targets(full_text)[: self._max_bullets]

        logger.info(
            "reflector_done",
            raw_chars=len(full_text),
            bullets_produced=len(parsed),
            bullets=[p["raw"] for p in parsed],
            update_targets=[p["update_target"] for p in parsed if p["update_target"]],
        )
        return parsed
