from __future__ import annotations

import pytest
from unittest.mock import patch

from layers.L2_creative.environment_manager import get_environment
from layers.L2_creative.prompt_builder import build_image_prompt
from layers.L2_creative.schemas import SceneShot
from layers.L2_creative.style_engine import get_template


def _shot(**overrides) -> SceneShot:
    data = {
        "scene_no": 1,
        "narration_segment": "咖啡涨价了。",
        "estimated_duration_sec": 5,
        "character_id": "su_wan",
        "environment_id": "coffee_shop",
        "time_of_day": "morning",
        "subject_action": "looking at receipt",
        "subject_emotion": "surprised",
        "key_props": ["coffee cup", "receipt"],
        "lighting_mood": "warm",
    }
    data.update(overrides)
    return SceneShot(**data)


def _prompt(shot: SceneShot | None = None, **kwargs) -> str:
    return build_image_prompt(shot or _shot(), get_template("hot_news_commentary"), **kwargs)


def test_prompt_contains_subject_face_and_hair():
    prompt = _prompt()

    assert "杏仁色眼眸" in prompt
    assert "深栗色长直发" in prompt


def test_prompt_contains_wardrobe_casual_when_choice_is_casual():
    prompt = _prompt(_shot(wardrobe_choice="casual"))

    assert "白色V领T恤" in prompt


def test_prompt_contains_outfit_override_when_wardrobe_custom():
    prompt = _prompt(_shot(wardrobe_choice="custom", outfit_override="红色连衣裙"))

    assert "红色连衣裙" in prompt


def test_prompt_contains_environment_props():
    prompt = _prompt()

    assert "手冲咖啡机" in prompt
    assert "原木长桌" in prompt


def test_prompt_contains_shot_type_description():
    prompt = _prompt(_shot(position={"camera_distance": "close_up"}))

    assert "face fills the entire frame" in prompt


def test_prompt_contains_camera_movement_when_not_static():
    prompt = _prompt(_shot(camera_movement="push_in"))

    assert "camera push in" in prompt


def test_prompt_omits_camera_movement_when_static():
    prompt = _prompt(_shot(camera_movement="static"))

    assert "camera static" not in prompt


def test_prompt_raises_on_unknown_character():
    shot = _shot()

    with patch("layers.L2_creative.prompt_builder.get_character", return_value=None):
        with pytest.raises(ValueError):
            build_image_prompt(shot, get_template("hot_news_commentary"), env=get_environment("coffee_shop"))


def test_prompt_includes_voice_type_hint_for_dialogue():
    prompt = _prompt(_shot(voice_type="dialogue"))

    assert "facing camera, lips visible" in prompt


def test_prompt_includes_key_props():
    prompt = _prompt()

    assert "coffee cup" in prompt
    assert "receipt" in prompt


def test_shot_hint_first_segment_picks_first_template():
    prompt = _prompt(_shot(scene_no=1), total_shots=5)

    assert "dramatic close-up" in prompt


def test_shot_hint_last_segment_picks_last_template():
    prompt = _prompt(_shot(scene_no=5), total_shots=5)

    assert "authoritative closing shot" in prompt


def test_shot_hint_omitted_when_total_shots_zero():
    prompt = _prompt(_shot(scene_no=1), total_shots=0)

    assert "dramatic close-up" not in prompt


# ── R5 改 30%: build_negative_prompt 测试 ──


def _negative(**overrides) -> str:
    from layers.L2_creative.prompt_builder import build_negative_prompt
    return build_negative_prompt(_shot(**overrides))


def test_negative_prompt_includes_base_quality_terms():
    """所有 shot 都应有基础质量负面词。"""
    neg = _negative()
    assert "low quality" in neg
    assert "blurry" in neg
    assert "deformed" in neg


def test_negative_prompt_includes_lighting_opposite_for_warm():
    """warm lighting → negative 包含 cold/harsh。"""
    neg = _negative(lighting_mood="warm")
    assert "cold blue" in neg or "harsh shadows" in neg


def test_negative_prompt_includes_lighting_opposite_for_cold():
    """cold lighting → negative 包含 warm/soft。"""
    neg = _negative(lighting_mood="cold")
    assert "warm orange" in neg or "soft glow" in neg


def test_negative_prompt_includes_voice_type_dialogue_negative():
    """dialogue → negative 拒绝侧脸/背对（必须正面）。"""
    neg = _negative(voice_type="dialogue")
    assert "facing away" in neg or "profile only" in neg or "mouth covered" in neg


def test_negative_prompt_includes_voice_type_narration_negative():
    """narration → negative 拒绝直视镜头（旁白主体不应破第四墙）。"""
    neg = _negative(voice_type="narration")
    assert "staring at camera" in neg or "breaking the fourth wall" in neg


def test_negative_prompt_includes_composition_opposite():
    """symmetric composition → negative 拒绝失衡构图。"""
    neg = _negative(composition="symmetric")
    assert "off-center" in neg or "unbalanced" in neg


def test_negative_prompt_appends_extra():
    """extra 参数追加到末尾。"""
    from layers.L2_creative.prompt_builder import build_negative_prompt
    neg = build_negative_prompt(_shot(), extra="ugly hands, mutated fingers")
    assert "ugly hands" in neg
