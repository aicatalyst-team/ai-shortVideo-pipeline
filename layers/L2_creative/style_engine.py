from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from config.settings import get_settings

log = logging.getLogger(__name__)


@dataclass
class StyleTemplate:
    name: str
    display_name: str
    core_concept: str
    visual_style: str
    caption_style: str
    hook_rule: str
    video_spec: str
    operators: list[str] = field(default_factory=list)
    image_prompt_suffix: str = ""
    kling_negative_prompt: str = ""
    aspect_ratio: str = "9:16"
    duration_range: tuple[int, int] = (5, 15)
    tags_prefix: list[str] = field(default_factory=list)
    positive_realism_suffix: str = ""
    negative_prompt: str = ""

    def system_prompt(self, extra_context: str = "") -> str:
        lines = [
            f"=== 风格档案：{self.display_name}（必须遵守）===",
            f"核心概念：{self.core_concept}",
            f"视觉风格：{self.visual_style}",
            f"字幕风格：{self.caption_style}",
            f"开场规则：{self.hook_rule}",
            f"规格：{self.video_spec}",
        ]
        if self.operators:
            lines.append(f"角色池：{'、'.join(self.operators)}")
        if extra_context:
            lines.append(extra_context)
        lines.append("=== 风格档案结束 ===")
        return "\n".join(lines)

    def enrich_image_prompt(self, raw_prompt: str) -> str:
        parts = [raw_prompt]
        if self.image_prompt_suffix:
            parts.append(self.image_prompt_suffix)
        if self.positive_realism_suffix:
            parts.append(self.positive_realism_suffix.strip())
        return ", ".join(parts)

    def get_negative_prompt(self, extra: str = "") -> str:
        parts = []
        if self.negative_prompt:
            parts.append(self.negative_prompt.strip())
        if self.kling_negative_prompt:
            parts.append(self.kling_negative_prompt.strip())
        if extra:
            parts.append(extra.strip())
        return ", ".join(parts)


_cache: dict[str, StyleTemplate] = {}


def _load_template(path: Path) -> StyleTemplate:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    dur = data.get("duration_range", [5, 15])
    return StyleTemplate(
        name=data["name"],
        display_name=data.get("display_name", data["name"]),
        core_concept=data["core_concept"],
        visual_style=data["visual_style"],
        caption_style=data["caption_style"],
        hook_rule=data["hook_rule"],
        video_spec=data.get("video_spec", "15-30秒，9:16竖版"),
        operators=data.get("operators", []),
        image_prompt_suffix=data.get("image_prompt_suffix", ""),
        kling_negative_prompt=data.get("kling_negative_prompt", ""),
        aspect_ratio=data.get("aspect_ratio", "9:16"),
        duration_range=(dur[0], dur[1]),
        tags_prefix=data.get("tags_prefix", []),
        positive_realism_suffix=data.get("positive_realism_suffix", ""),
        negative_prompt=data.get("negative_prompt", ""),
    )


def load_all_templates(force: bool = False) -> dict[str, StyleTemplate]:
    global _cache
    if _cache and not force:
        return _cache

    tpl_dir = get_settings().style_templates_dir
    if not tpl_dir.is_dir():
        log.warning("风格模板目录不存在: %s", tpl_dir)
        return {}

    _cache = {}
    for p in sorted(tpl_dir.glob("*.yaml")):
        try:
            tpl = _load_template(p)
            _cache[tpl.name] = tpl
            log.info("已加载风格模板: %s (%s)", tpl.name, tpl.display_name)
        except Exception as e:
            log.error("加载风格模板失败 %s: %s", p.name, e)

    return _cache


def get_template(name: str) -> StyleTemplate:
    templates = load_all_templates()
    if name not in templates:
        available = list(templates.keys())
        raise KeyError(f"风格模板 '{name}' 不存在，可用: {available}")
    return templates[name]


def list_template_names() -> list[str]:
    return list(load_all_templates().keys())
