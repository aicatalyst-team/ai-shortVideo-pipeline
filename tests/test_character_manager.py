"""R1.1（W2 D8）角色卡扩展验收单测。

覆盖：
  - 4 个内置角色加载不爆错
  - 新增 6 类字段（identity/appearance/wardrobe/props/voice/visual_refs）可属性访问
  - v5 §五 D8 验收命令：character.wardrobe.casual 能读到
  - 旧字段向后兼容（description/visual_tags/ref_images/max_consecutive_shots）
  - 未填字段返回空字符串/空列表，不爆 AttributeError
"""
from __future__ import annotations

import pytest

from layers.L2_creative.character_manager import (
    Appearance,
    CharacterProfile,
    Identity,
    Props,
    VisualRefs,
    Voice,
    Wardrobe,
    _load_characters,
    get_character,
    list_characters,
)


CORE_CHARACTERS = ["su_wan", "lin_yue", "chen_xing", "ye_cheng"]


def test_all_four_characters_loaded():
    chars = _load_characters(force=True)
    for key in CORE_CHARACTERS:
        assert key in chars, f"角色 {key} 未加载"


def test_d8_acceptance_command():
    """v5 §五 D8 验收命令：get_character('su_wan').wardrobe.casual 必须能访问到值"""
    c = get_character("su_wan")
    assert c is not None
    casual = c.wardrobe.casual
    assert isinstance(casual, str)
    assert len(casual) > 0, "苏晚的 wardrobe.casual 应从 description 拆出，不应为空"


@pytest.mark.parametrize("key", CORE_CHARACTERS)
def test_new_field_groups_are_dataclass_instances(key):
    """新增 6 类字段必须是 dataclass 实例，不能是 None / dict（避免 .X 爆 AttributeError）"""
    c = get_character(key)
    assert isinstance(c.identity, Identity)
    assert isinstance(c.appearance, Appearance)
    assert isinstance(c.wardrobe, Wardrobe)
    assert isinstance(c.props, Props)
    assert isinstance(c.voice, Voice)
    assert isinstance(c.visual_refs, VisualRefs)


@pytest.mark.parametrize("key", CORE_CHARACTERS)
def test_unfilled_fields_return_empty_not_none(key):
    """未填的字段必须返回空字符串/空列表，访问 .X 不应该返回 None"""
    c = get_character(key)
    # identity 三项当前都是用户待填，期望空串
    assert isinstance(c.identity.age, str)
    assert isinstance(c.identity.profession, str)
    assert isinstance(c.identity.personality, str)
    # props.items 期望空 list
    assert isinstance(c.props.items, list)
    # voice 三项期望空串
    assert isinstance(c.voice.tts_id, str)
    assert isinstance(c.voice.pace, str)
    assert isinstance(c.voice.emotion, str)


@pytest.mark.parametrize("key", CORE_CHARACTERS)
def test_appearance_hair_migrated_from_description(key):
    """4 个角色的 appearance.hair 应已从 description 拆出非空值"""
    c = get_character(key)
    assert len(c.appearance.hair) > 0, f"{key} 的 appearance.hair 应从 description 拆出"


@pytest.mark.parametrize("key", CORE_CHARACTERS)
def test_wardrobe_casual_migrated_from_description(key):
    """4 个角色的 wardrobe.casual 应已从 description 拆出非空值"""
    c = get_character(key)
    assert len(c.wardrobe.casual) > 0, f"{key} 的 wardrobe.casual 应从 description 拆出"


def test_visual_refs_front_aligned_with_ref_images():
    """visual_refs.front 应与 ref_images.front 一致（过渡期向后兼容）"""
    c = get_character("su_wan")
    assert c.visual_refs.front == c.ref_images.get("front")


@pytest.mark.parametrize("key", CORE_CHARACTERS)
def test_backward_compat_legacy_fields_intact(key):
    """旧字段必须保留：description / visual_tags / ref_images / compatible_styles / max_consecutive_shots"""
    c = get_character(key)
    assert c.description, f"{key}.description 不应为空"
    assert c.visual_tags, f"{key}.visual_tags 不应为空"
    assert c.ref_images.get("front"), f"{key}.ref_images.front 不应为空"
    assert isinstance(c.compatible_styles, list)
    assert c.max_consecutive_shots == 4


def test_list_characters_returns_at_least_four():
    chars = list_characters()
    assert len(chars) >= 4
    keys = {c.key for c in chars}
    for k in CORE_CHARACTERS:
        assert k in keys
