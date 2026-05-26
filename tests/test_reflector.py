"""Tests for Reflector — context building, bullet extraction, dedup, merge body dedup."""

import pytest
from robocode.agent.reflector import (
    Reflector,
    _build_reflection_context,
    _extract_bullets,
    deduplicate_bullets,
)
from robocode.agent.experience_manager import ExperienceManager


# ── _build_reflection_context ──────────────────────────────────


class TestBuildContext:
    def test_empty_inputs(self):
        assert _build_reflection_context([], None, None).strip() == ""

    def test_transcript_and_physics(self):
        ctx = _build_reflection_context(
            transcript=[
                {"role": "user", "content": "移动到 x=200"},
                {"role": "tool_call", "tool": "move_robot_xyz", "params": "x=200, y=0, z=150"},
                {"role": "tool_result", "success": True, "message": "执行完成"},
            ],
            physics={
                "move_robot_xyz": {
                    "speed_groups": {
                        0.5: {
                            "avg_max_delta": 1.2,
                            "count": 5,
                            "avg_duration_ms": 3000,
                            "samples": [
                                {
                                    "before": [1, 2, 3, 4, 5, 6],
                                    "after": [2, 3, 4, 5, 6, 7],
                                    "params": {"x": 200},
                                }
                            ],
                        },
                    }
                }
            },
            annotations=None,
        )
        assert "移动到 x=200" in ctx
        assert "move_robot_xyz" in ctx
        assert "关节角度" in ctx
        assert "delta=[1, 1, 1, 1, 1, 1]" in ctx

    def test_transcript_with_feedback(self):
        ctx = _build_reflection_context(
            transcript=[
                {"role": "user", "content": "归零"},
                {"role": "tool_call", "tool": "move_robot_home", "params": ""},
                {"role": "tool_result", "success": False, "message": "超限"},
            ],
            physics=None,
            annotations={"motion": {"free_texts": ["归零失败，位置不对"]}},
        )
        assert "归零" in ctx
        assert "move_robot_home" in ctx
        assert "归零失败，位置不对" in ctx
        assert "❌" in ctx or "失败" in ctx


# ── _extract_bullets ───────────────────────────────────────────


class TestExtractBullets:
    def test_standard_format(self):
        text = "- [L2] move_robot_xyz z<50 时 IK 无解\n- [PARAM] speed_ratio 0.3~0.5 最佳"
        bullets = _extract_bullets(text)
        assert len(bullets) == 2
        assert "[L2]" in bullets[0]
        assert "[PARAM]" in bullets[1]

    def test_mixed_with_noise(self):
        text = """以下是分析结果：
- [L2] 某条洞察
其他文字
- [PARAM] 另一条洞察
总结段落"""
        bullets = _extract_bullets(text)
        assert len(bullets) == 2

    def test_no_bullets(self):
        text = "这段文字没有任何 bullets"
        result = _extract_bullets(text)
        assert len(result) == 1
        assert "[REFLECT]" in result[0]

    def test_numbered_list_format(self):
        text = "1. [L2] 数字列表格式"
        bullets = _extract_bullets(text)
        assert len(bullets) == 1
        assert "[L2]" in bullets[0]

    def test_bold_format(self):
        text = "- **PARAM** 加粗格式而不是方括号"
        bullets = _extract_bullets(text)
        assert len(bullets) == 1

    def test_reversed_format(self):
        text = "[L2] - 顺序颠倒的格式"
        bullets = _extract_bullets(text)
        assert len(bullets) == 1
        assert "[L2]" in bullets[0]

    def test_empty_string(self):
        assert _extract_bullets("") == []


# ── deduplicate_bullets ────────────────────────────────────────


class TestDeduplicateBullets:
    def test_exact_duplicate(self):
        existing = ["- [PARAM] speed_ratio 0.3~0.5 最佳范围"]
        new = ["- [PARAM] speed_ratio 0.3~0.5 最佳范围"]
        assert deduplicate_bullets(new, existing) == []

    def test_no_duplicates(self):
        existing = ["- [L2] 某条洞察"]
        new = ["- [PARAM] 完全不同的内容"]
        assert len(deduplicate_bullets(new, existing)) == 1

    def test_partial_similarity(self):
        existing = ["- [PARAM] speed_ratio 0.3~0.5 是最佳范围"]
        new = ["- [PARAM] speed_ratio 0.3~0.5 是最佳范围，建议使用"]
        result = deduplicate_bullets(new, existing, threshold=0.75)
        assert len(result) == 0

    def test_empty_inputs(self):
        assert deduplicate_bullets([], []) == []
        assert deduplicate_bullets(["- [L2] x"], []) == ["- [L2] x"]
        assert deduplicate_bullets([], ["- [L2] x"]) == []

    def test_multiple_mixed(self):
        existing = [
            "- [PARAM] speed_ratio 0.3~0.5 最佳",
            "- [CAUTION] z<50 IK 无解",
        ]
        new = [
            "- [PARAM] speed_ratio 0.3~0.5 最佳范围",  # similar to existing[0]
            "- [L2] 全新洞察",  # unique
            "- [CAUTION] z<50 时逆运动学失败",  # different enough from existing[1]
        ]
        result = deduplicate_bullets(new, existing)
        assert "- [L2] 全新洞察" in result
        assert "- [CAUTION] z<50 时逆运动学失败" in result


# ── Reflector.reflect with mock provider ───────────────────────


class FakeProvider:
    """Fake LLM provider that yields predefined text."""

    def __init__(self, response: str):
        self._response = response

    async def stream(self, system, messages, tools):
        from robocode.llm.base import StreamEvent

        for chunk in self._response.split("\n"):
            yield StreamEvent(kind="text_delta", payload={"delta": chunk + "\n"})
        yield StreamEvent(kind="end_turn", payload={})


class TestReflectorReflect:
    @pytest.mark.asyncio
    async def test_reflect_with_bullets(self):
        provider = FakeProvider("- [PARAM] speed_ratio 0.3 最佳\n- [CAUTION] z<50 有风险")
        reflector = Reflector(provider=provider, max_bullets=8)
        bullets = await reflector.reflect(
            transcript=[{"role": "user", "content": "移动到 x=200"}],
            physics={
                "t": {
                    "speed_groups": {
                        0.3: {
                            "avg_max_delta": 1.2,
                            "count": 5,
                            "avg_duration_ms": 3000,
                            "samples": [],
                        }
                    }
                }
            },
        )
        assert len(bullets) == 2

    @pytest.mark.asyncio
    async def test_reflect_empty_context(self):
        provider = FakeProvider("- [L2] 应该不会被调用")
        reflector = Reflector(provider=provider)
        bullets = await reflector.reflect()
        assert bullets == []

    @pytest.mark.asyncio
    async def test_reflect_max_bullets(self):
        provider = FakeProvider("\n".join(f"- [L2] 洞察 {i}" for i in range(10)))
        reflector = Reflector(provider=provider, max_bullets=3)
        bullets = await reflector.reflect(
            transcript=[{"role": "user", "content": "test"}],
            annotations={"general": {"free_texts": ["测试反馈"]}},
        )
        assert len(bullets) == 3


# ── ExperienceManager._merge_bodies ────────────────────────────


class TestMergeBodies:
    def test_merge_deduplicates_bullets(self):
        target = "## 建议\n\n- [RULE] 建议1\n- [PARAM] speed 0.3 最佳"
        source = "## 建议\n\n- [RULE] 建议2\n- [PARAM] speed 0.3 最佳\n- [L2] 新洞察"
        result = ExperienceManager._merge_bodies(target, source, "source.md")
        assert "[PARAM] speed 0.3 最佳" in result
        assert "[L2] 新洞察" in result
        param_count = result.count("- [PARAM] speed 0.3 最佳")
        assert param_count == 1, f"expected 1 occurrence, got {param_count}"

    def test_merge_no_bullets(self):
        target = "## 物理规律\n- speed=0.3: avg=1.2"
        source = "## 物理规律\n- speed=0.8: avg=3.5"
        result = ExperienceManager._merge_bodies(target, source, "source.md")
        assert "## 建议" not in result

    def test_merge_target_only_has_bullets(self):
        target = "## 建议\n\n- [L2] 只有target有"
        source = "## 物理规律\n- speed=0.8: avg=3.5"
        result = ExperienceManager._merge_bodies(target, source, "source.md")
        assert "[L2] 只有target有" in result

    def test_merge_source_only_has_bullets(self):
        target = "## 物理规律\n- speed=0.3: avg=1.2"
        source = "## 建议\n\n- [CAUTION] 只有source有"
        result = ExperienceManager._merge_bodies(target, source, "source.md")
        assert "[CAUTION] 只有source有" in result
