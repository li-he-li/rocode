"""技能自动发现 — 扫描 robocode/skills/ 目录喵~

每个技能 = 一个子文件夹，包含 skill.md (YAML frontmatter + Markdown 正文)。
用 /<folder_name> 调用。
"""

import re
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional

SKILLS_DIR = Path(__file__).parent.parent / "skills"


@dataclass
class Skill:
    """技能数据结构喵~"""

    name: str  # 文件夹名，用于 /<name> 调用
    description: str  # 技能描述
    category: str = ""  # 分类: calibration/detection/application
    requires_human: bool = True  # 是否需要人工操作
    script: str = ""  # 启动脚本路径
    output_files: List[str] = field(default_factory=list)  # 产出文件
    risk_level: str = "L1"  # 风险级别
    body: str = ""  # Markdown 正文（技能指引）


def load_skills(skills_dir: Optional[Path] = None) -> Dict[str, Skill]:
    """扫描 skills/ 子文件夹，每个文件夹内的 skill.md 解析为一个 Skill 喵~"""
    if skills_dir is None:
        skills_dir = SKILLS_DIR
    skills: dict[str, Skill] = {}
    if not skills_dir.exists():
        return skills

    for folder in sorted(skills_dir.iterdir()):
        if not folder.is_dir():
            continue
        md_path = folder / "skill.md"
        if not md_path.exists():
            continue
        content = md_path.read_text(encoding="utf-8")
        skill = _parse_skill_md(content, folder.name)
        if skill:
            skills[folder.name] = skill
    return skills


def _parse_skill_md(content: str, folder_name: str) -> Optional[Skill]:
    """解析 skill.md 的 YAML frontmatter + Markdown 正文喵~"""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if not match:
        return None
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return None

    return Skill(
        name=folder_name,
        description=meta.get("description", ""),
        category=meta.get("category", ""),
        requires_human=meta.get("requires_human", True),
        script=meta.get("script", ""),
        output_files=meta.get("output_files", []),
        risk_level=meta.get("risk_level", "L1"),
        body=match.group(2).strip(),
    )
