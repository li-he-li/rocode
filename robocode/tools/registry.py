"""Tool and skill registry — registration, schema generation, discovery."""

from dataclasses import dataclass, field


@dataclass
class ToolEntry:
    name: str
    description: str
    parameters: dict
    risk_level: str  # "L0" | "L1" | "L2"
    timeout_s: float = 30.0
    backend: str = "sdk"
    is_skill: bool = False

    def to_openai_schema(self) -> dict:
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
    script_path: str = ""
    requires_human: bool = True
    output_files: list[str] = field(default_factory=list)
    category: str = ""

    def __post_init__(self):
        self.is_skill = True


class ToolRegistry:
    def __init__(self):
        self._entries: dict[str, ToolEntry] = {}

    def register(self, entry: ToolEntry):
        if entry.name in self._entries:
            raise ValueError(f"Tool/skill '{entry.name}' already registered")
        self._entries[entry.name] = entry

    def get(self, name: str) -> ToolEntry | None:
        return self._entries.get(name)

    def list_tools(self) -> list[ToolEntry]:
        return [e for e in self._entries.values() if not e.is_skill]

    def list_skills(self) -> list[SkillEntry]:
        return [e for e in self._entries.values() if isinstance(e, SkillEntry)]

    def all_schemas(self) -> list[dict]:
        return [e.to_openai_schema() for e in self._entries.values()]

    def filter_by_risk(self, risk_level: str) -> list[ToolEntry]:
        return [e for e in self._entries.values() if e.risk_level == risk_level]

    def __len__(self):
        return len(self._entries)
