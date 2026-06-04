from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).resolve().parents[2] / "config" / "skills"
_cache: dict[str, "CreativeSkillConfig"] = {}
_alias_cache: dict[str, str] = {}


class CreativeSkillConfig(BaseModel):
    """Product-facing creation skill loaded from config/skills/*.yaml."""

    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    use_cases: list[str] = Field(default_factory=list)
    focus: list[str] = Field(default_factory=list)
    default_prompt_style: str = "hot_news_commentary"
    default_intensity: str = "标准增强"
    default_emotion: str = ""
    default_subject: str = ""
    shot_template_key: str = ""
    prompt_director_config_key: str = ""


def _norm_key(value: str) -> str:
    return str(value or "").strip().lower()


def _load_skill(path: Path) -> CreativeSkillConfig:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return CreativeSkillConfig.model_validate(data)


def load_creative_skills(force: bool = False) -> dict[str, CreativeSkillConfig]:
    """Load all Phase P creative skills from config/skills."""
    global _cache, _alias_cache
    if _cache and not force:
        return _cache

    _cache = {}
    _alias_cache = {}
    if not _SKILLS_DIR.is_dir():
        log.warning("[creative_skills] skills dir not found: %s", _SKILLS_DIR)
        return _cache

    for path in sorted(_SKILLS_DIR.glob("*.yaml")):
        try:
            skill = _load_skill(path)
            _cache[skill.id] = skill
            for key in [skill.id, skill.name, *skill.aliases]:
                normalized = _norm_key(key)
                if normalized:
                    _alias_cache[normalized] = skill.id
        except Exception as exc:
            log.error("[creative_skills] load failed %s: %s", path.name, exc)

    return _cache


def list_creative_skills() -> list[CreativeSkillConfig]:
    """Return skills in stable id order."""
    return [load_creative_skills()[key] for key in sorted(load_creative_skills())]


def get_creative_skill(key_or_alias: str) -> CreativeSkillConfig | None:
    """Resolve a skill by id / display name / alias."""
    load_creative_skills()
    skill_id = _alias_cache.get(_norm_key(key_or_alias))
    if not skill_id:
        return None
    return _cache.get(skill_id)


def format_creative_skills_for_feishu(active_id: str = "") -> str:
    """Format available skills for Feishu command help."""
    skills = list_creative_skills()
    if not skills:
        return "暂无可用 Skill，请检查 config/skills/*.yaml"

    lines = ["可用创作 Skill："]
    for skill in skills:
        marker = "> " if skill.id == active_id else "  "
        aliases = " / ".join(skill.aliases[:4])
        focus = "、".join(skill.focus[:4])
        lines.append(f"{marker}{skill.name}（{skill.id}）")
        lines.append(f"    别名：{aliases}")
        lines.append(f"    适合：{skill.description}")
        if focus:
            lines.append(f"    重点：{focus}")
    lines.append("\n切换：发送「Skill 电影」/「Skill 抖音」/「Skill 产品」")
    return "\n".join(lines)
