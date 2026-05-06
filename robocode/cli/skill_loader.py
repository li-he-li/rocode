"""Auto-discover skills from robocode/skills/ folder.
Each skill = a subfolder containing skill.md with YAML frontmatter.
Use /<folder_name> to invoke.
"""

import re
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional

SKILLS_DIR = Path(__file__).parent.parent / "skills"


@dataclass
class Skill:
    name: str  # folder name, used for /<name> invocation
    description: str
    category: str = ""
    requires_human: bool = True
    script: str = ""
    output_files: List[str] = field(default_factory=list)
    risk_level: str = "L1"
    body: str = ""


def load_skills(skills_dir: Optional[Path] = None) -> Dict[str, Skill]:
    """Scan skills/ subfolders, each containing skill.md. Returns {folder_name: Skill}."""
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
    """Parse YAML frontmatter + markdown body from skill.md."""
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
