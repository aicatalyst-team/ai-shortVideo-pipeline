"""R1.2 环境卡新建验收测试。"""

from dataclasses import is_dataclass

import pytest

from layers.L2_creative import environment_manager as em
from layers.L2_creative.environment_manager import (
    EnvironmentProfile,
    Lighting,
    Mood,
    get_default_environment,
    get_environment,
    get_environments_for_style,
    list_environments,
)


ENVIRONMENT_KEYS = [
    "coffee_shop",
    "classroom",
    "bedroom",
    "park",
    "office",
    "street",
    "kitchen",
    "car_interior",
    "study_room",
    "seaside",
]


def test_load_all_environments():
    environments = em._load_environments(force=True)
    assert set(ENVIRONMENT_KEYS).issubset(environments.keys())
    assert len(environments) >= 10


def test_default_environment_is_coffee_shop():
    env = get_default_environment()
    assert env is not None
    assert env.key == "coffee_shop"


def test_v5_acceptance_command_props_is_list():
    env = get_environment("coffee_shop")
    assert env is not None
    assert isinstance(env.props, list)
    assert "手冲咖啡机" in env.props


def test_get_environment_by_display_name():
    env = get_environment("咖啡馆")
    assert env is not None
    assert env.key == "coffee_shop"


def test_get_unknown_environment_returns_none():
    assert get_environment("not_exists") is None


def test_list_environments_returns_profiles():
    environments = list_environments()
    assert len(environments) >= 10
    assert all(isinstance(env, EnvironmentProfile) for env in environments)


def test_get_environments_for_style_returns_matches():
    environments = get_environments_for_style("cute_healing")
    keys = {env.key for env in environments}
    assert {"coffee_shop", "bedroom", "park", "kitchen", "seaside"}.issubset(keys)


def test_get_environments_for_unknown_style_returns_only_open_environments():
    assert get_environments_for_style("unknown_style") == []


@pytest.mark.parametrize("key", ENVIRONMENT_KEYS)
def test_environment_profile_dataclass(key):
    env = get_environment(key)
    assert env is not None
    assert is_dataclass(env)
    assert isinstance(env, EnvironmentProfile)


@pytest.mark.parametrize("key", ENVIRONMENT_KEYS)
def test_nested_dataclasses_are_present(key):
    env = get_environment(key)
    assert env is not None
    assert isinstance(env.lighting, Lighting)
    assert isinstance(env.mood, Mood)


@pytest.mark.parametrize("key", ENVIRONMENT_KEYS)
def test_core_text_fields_are_strings(key):
    env = get_environment(key)
    assert env is not None
    assert isinstance(env.key, str)
    assert isinstance(env.display_name, str)
    assert isinstance(env.description, str)
    assert isinstance(env.visual_tags, str)


@pytest.mark.parametrize("key", ENVIRONMENT_KEYS)
def test_props_are_top_level_list(key):
    env = get_environment(key)
    assert env is not None
    assert isinstance(env.props, list)
    assert all(isinstance(item, str) for item in env.props)


@pytest.mark.parametrize("key", ENVIRONMENT_KEYS)
def test_lighting_fields_are_strings(key):
    env = get_environment(key)
    assert env is not None
    assert isinstance(env.lighting.style, str)
    assert isinstance(env.lighting.intensity, str)
    assert isinstance(env.lighting.direction, str)
    assert isinstance(env.lighting.color_temp, str)


@pytest.mark.parametrize("key", ENVIRONMENT_KEYS)
def test_mood_fields_are_safe(key):
    env = get_environment(key)
    assert env is not None
    assert isinstance(env.mood.primary, str)
    assert isinstance(env.mood.secondary, str)
    assert isinstance(env.mood.keywords, list)


@pytest.mark.parametrize("key", ENVIRONMENT_KEYS)
def test_visual_tags_are_single_line(key):
    env = get_environment(key)
    assert env is not None
    assert "\n" not in env.visual_tags
    assert "  " not in env.visual_tags


@pytest.mark.parametrize("key", ENVIRONMENT_KEYS)
def test_compatible_styles_are_list(key):
    env = get_environment(key)
    assert env is not None
    assert isinstance(env.compatible_styles, list)
    assert all(isinstance(item, str) for item in env.compatible_styles)


def test_loader_missing_fields_return_defaults():
    env = EnvironmentProfile(
        key="empty",
        display_name="",
        description="",
        visual_tags="",
    )
    assert env.lighting.style == ""
    assert env.props == []
    assert env.mood.keywords == []
    assert env.compatible_styles == []


def test_helper_load_lighting_handles_invalid_input():
    lighting = em._load_lighting(None)
    assert lighting == Lighting()


def test_helper_load_mood_handles_invalid_input():
    mood = em._load_mood({"keywords": "bad"})
    assert mood.primary == ""
    assert mood.secondary == ""
    assert mood.keywords == []


def test_helper_load_props_handles_invalid_input():
    assert em._load_props({"props": ["bad"]}) == []
    assert em._load_props(None) == []


def test_load_environments_force_refresh_keeps_cache_shape():
    first = em._load_environments(force=True)
    second = em._load_environments()
    assert first is second
    assert isinstance(second, dict)


def test_bad_environment_does_not_block_good_ones(tmp_path, monkeypatch):
    cfg = tmp_path / "environments.yaml"
    cfg.write_text(
        """
default_environment: good
good:
  display_name: 好环境
  description: 正常
  lighting: {}
  props: [道具]
  mood: {}
  visual_tags: >
    a
    b
  compatible_styles: []
bad:
  display_name: 坏环境
  description: 错误数据
  lighting: {}
  props: []
  mood: {}
  visual_tags:
    - not
    - string
  compatible_styles: {}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(em, "_get_environments_path", lambda: cfg)
    environments = em._load_environments(force=True)
    assert environments["good"].visual_tags == "a b"
    assert environments["bad"].compatible_styles == []

    monkeypatch.undo()
    em._load_environments(force=True)


def test_path_resolves_next_to_characters_config():
    path = em._get_environments_path()
    assert path.name == "environments.yaml"
    assert path.parent.name == "config"
