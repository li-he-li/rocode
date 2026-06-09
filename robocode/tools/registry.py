"""工具与技能注册中心 — 注册、schema 生成、按风险过滤喵~"""

from dataclasses import dataclass, field


@dataclass
class ToolEntry:
    """工具条目 — 描述一个可被 Agent 调用的工具喵~"""

    name: str  # 工具名（唯一 ID）
    description: str  # 功能描述
    parameters: dict  # OpenAI function calling 参数 schema
    risk_level: str  # 风险级别: "L0" | "L1" | "L2"
    timeout_s: float = 30.0  # 执行超时秒数
    backend: str = "sdk"  # 后端类型
    is_skill: bool = False  # 是否为技能（而非普通工具）

    def to_openai_schema(self) -> dict:
        """转为 OpenAI function calling 格式的 schema 喵~"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class SkillEntry(ToolEntry):
    """技能条目 — 继承工具，额外带有脚本路径和人工操作标记喵~"""

    script_path: str = ""
    requires_human: bool = True  # 是否需要人工操作 GUI
    output_files: list[str] = field(default_factory=list)  # 技能产出的文件列表
    category: str = ""  # 分类: calibration/detection/application

    def __post_init__(self):
        self.is_skill = True


class ToolRegistry:
    """工具注册中心 — 统一管理工具和技能的注册与查询喵~"""

    def __init__(self):
        self._entries: dict[str, ToolEntry] = {}

    def register(self, entry: ToolEntry):
        """注册一个工具或技能，重名抛异常喵~"""
        if entry.name in self._entries:
            raise ValueError(f"Tool/skill '{entry.name}' already registered")
        self._entries[entry.name] = entry

    def get(self, name: str) -> ToolEntry | None:
        """按名获取工具条目喵~"""
        return self._entries.get(name)

    def list_tools(self) -> list[ToolEntry]:
        """列出所有普通工具（不含技能）喵~"""
        return [e for e in self._entries.values() if not e.is_skill]

    def list_skills(self) -> list[SkillEntry]:
        """列出所有技能喵~"""
        return [e for e in self._entries.values() if isinstance(e, SkillEntry)]

    def all_schemas(self) -> list[dict]:
        """生成所有条目的 OpenAI schema 列表喵~"""
        return [e.to_openai_schema() for e in self._entries.values()]

    def filter_by_risk(self, risk_level: str) -> list[ToolEntry]:
        """按风险级别过滤工具喵~"""
        return [e for e in self._entries.values() if e.risk_level == risk_level]

    def __len__(self):
        return len(self._entries)
