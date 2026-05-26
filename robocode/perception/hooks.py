"""Hook 系统 — 工具调用的前置/后置 VLM 观察钩子喵~

钩子规则从经验文件 experience/vlm/vlm-hooks.md 加载。
格式: - [意图|HOOK] @tool_name pre|post:action "prompt_template"
"""

import re
from pathlib import Path
from dataclasses import dataclass

EXPERIENCE_ROOT = Path(__file__).resolve().parent.parent / "experience"  # robocode/experience/
HOOKS_FILE = EXPERIENCE_ROOT / "vlm" / "vlm-hooks.md"

# VLM 工具自身不触发 hooks，防止循环
_VLM_TOOLS = {"observe", "locate"}

# 默认内置钩子规则 — 经验文件不存在时使用
_BUILTIN_HOOKS = [
    ("move_robot_xyz", "pre", "observe", "拍摄工作区当前状态，确认目标位置和无障碍物"),
    ("move_robot_xyz", "post", "observe", "移到新位置后，观察当前位置和状态是否符合预期"),
    ("move_robot_joints", "pre", "observe", "当前视野是否清楚看到工作区"),
    ("servo_gripper_control", "post", "observe", "夹爪闭合后，拍一张照片确认物体是否在夹爪中"),
    ("control_suction", "post", "observe", "吸盘开启后，拍一张照片确认物体是否被吸附"),
]


@dataclass
class HookRule:
    tool_name: str  # move_robot_xyz
    phase: str  # "pre" | "post"
    action: str  # "observe" | "locate"
    prompt_template: str  # "确认目标位置和无障碍物"
    auto: bool = True


class HookRegistry:
    """从经验文件加载钩子规则，提供 pre/post hook 查询喵~"""

    def __init__(self, hooks_file: Path | None = None):
        self._hooks: list[HookRule] = []
        self._load(hooks_file or HOOKS_FILE)

    def get_pre_hooks(self, tool_name: str) -> list[HookRule]:
        if tool_name in _VLM_TOOLS:
            return []
        return [h for h in self._hooks if h.tool_name == tool_name and h.phase == "pre"]

    def get_post_hooks(self, tool_name: str) -> list[HookRule]:
        if tool_name in _VLM_TOOLS:
            return []
        return [h for h in self._hooks if h.tool_name == tool_name and h.phase == "post"]

    @property
    def hook_count(self) -> int:
        return len(self._hooks)

    # ── 内部 ──────────────────────────────────────────────────────

    def _load(self, path: Path):
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8")
                parsed = self._parse_hooks(content)
                if parsed:
                    self._hooks = parsed
                    return
            except Exception:
                pass
        # Fallback: 内置默认规则
        self._hooks = self._build_defaults()

    @staticmethod
    def _parse_hooks(content: str) -> list[HookRule]:
        """解析经验文件中的钩子规则喵~"""
        rules: list[HookRule] = []
        _HOOK_RE = re.compile(r"-\s*\[.*?\|HOOK\]\s*@(\w+)\s+(pre|post):(\w+)\s*\"(.+?)\"\s*$")
        for line in content.split("\n"):
            m = _HOOK_RE.search(line.strip())
            if m:
                rules.append(
                    HookRule(
                        tool_name=m.group(1),
                        phase=m.group(2),
                        action=m.group(3),
                        prompt_template=m.group(4),
                    )
                )
        return rules

    @staticmethod
    def _build_defaults() -> list[HookRule]:
        return [
            HookRule(tool_name=t, phase=p, action=a, prompt_template=pt)
            for t, p, a, pt in _BUILTIN_HOOKS
        ]
