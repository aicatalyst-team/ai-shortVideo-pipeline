from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from config.settings import get_settings

log = logging.getLogger(__name__)


@dataclass
class Lighting:
    style: str = ""
    intensity: str = ""
    direction: str = ""
    color_temp: str = ""


@dataclass
class Mood:
    primary: str = ""
    secondary: str = ""
    keywords: list[str] = field(default_factory=list)


@dataclass
class EnvironmentProfile:
    key: str
    display_name: str
    description: str
    visual_tags: str
    lighting: Lighting = field(default_factory=Lighting)
    props: list[str] = field(default_factory=list)
    mood: Mood = field(default_factory=Mood)
    compatible_styles: list[str] = field(default_factory=list)


_cache: dict[str, EnvironmentProfile] | None = None
_default_key: str = ""


def _get_environments_path() -> Path:
    return Path(get_settings().characters_config_path).resolve().parent / "environments.yaml"


def _load_lighting(d: dict) -> Lighting:
    if not isinstance(d, dict):
        d = {}
    return Lighting(
        style=str(d.get("style") or ""),
        intensity=str(d.get("intensity") or ""),
        direction=str(d.get("direction") or ""),
        color_temp=str(d.get("color_temp") or ""),
    )


def _load_mood(d: dict) -> Mood:
    if not isinstance(d, dict):
        d = {}
    keywords = d.get("keywords") or []
    if not isinstance(keywords, list):
        keywords = []
    return Mood(
        primary=str(d.get("primary") or ""),
        secondary=str(d.get("secondary") or ""),
        keywords=[str(x) for x in keywords if x is not None],
    )


def _load_props(d) -> list[str]:
    if not isinstance(d, list):
        return []
    return [str(x) for x in d if x is not None]


def _load_environments(force: bool = False) -> dict[str, EnvironmentProfile]:
    global _cache, _default_key
    if _cache is not None and not force:
        return _cache

    cfg_path = _get_environments_path()
    if not cfg_path.exists():
        log.warning("环境配置不存在: %s", cfg_path)
        _cache = {}
        _default_key = ""
        return _cache

    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        log.warning("环境配置格式错误: %s", cfg_path)
        _cache = {}
        _default_key = ""
        return _cache

    _default_key = str(raw.pop("default_environment", "") or "")
    result: dict[str, EnvironmentProfile] = {}

    for key, data in raw.items():
        if not isinstance(data, dict):
            continue
        try:
            tags = data.get("visual_tags") or ""
            if isinstance(tags, str):
                tags = " ".join(tags.split())
            else:
                tags = ""

            styles = data.get("compatible_styles") or []
            if not isinstance(styles, list):
                styles = []

            result[str(key)] = EnvironmentProfile(
                key=str(key),
                display_name=str(data.get("display_name") or ""),
                description=str(data.get("description") or ""),
                visual_tags=tags,
                lighting=_load_lighting(data.get("lighting") or {}),
                props=_load_props(data.get("props") or []),
                mood=_load_mood(data.get("mood") or {}),
                compatible_styles=[str(x) for x in styles if x is not None],
            )
        except Exception as e:
            log.error("加载环境失败 %s: %s", key, e)

    _cache = result
    log.info("已加载 %d 个环境配置", len(result))
    return _cache


def get_environment(name: str) -> EnvironmentProfile | None:
    environments = _load_environments()
    if name in environments:
        return environments[name]
    for env in environments.values():
        if env.display_name == name:
            return env
    return None


def get_default_environment() -> EnvironmentProfile | None:
    environments = _load_environments()
    if _default_key and _default_key in environments:
        return environments[_default_key]
    return next(iter(environments.values()), None)


def list_environments() -> list[EnvironmentProfile]:
    return list(_load_environments().values())


def get_environments_for_style(style_name: str) -> list[EnvironmentProfile]:
    return [
        env
        for env in _load_environments().values()
        if not env.compatible_styles or style_name in env.compatible_styles
    ]
