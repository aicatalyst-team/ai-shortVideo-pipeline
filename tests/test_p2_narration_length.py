from __future__ import annotations

import pytest
from pydantic import ValidationError

from layers.L2_creative.chains_v2 import _build_creative_system_prompt
from layers.L2_creative.schemas import SceneShot, get_narration_char_limit
from layers.L2_creative.style_engine import StyleTemplate


def valid_shot_dict(duration: float = 5.0, narration: str = "科技带来便利") -> dict:
    return {
        "scene_no": 1,
        "narration_segment": narration,
        "estimated_duration_sec": duration,
        "character_id": "su_wan",
        "environment_id": "coffee_shop",
        "time_of_day": "morning",
        "subject_action": "looking at a receipt beside a coffee cup",
        "subject_emotion": "surprised",
        "wardrobe_choice": "casual",
        "key_props": ["coffee cup", "receipt"],
        "position": {
            "subject_position": "center",
            "camera_distance": "medium",
            "camera_angle": "eye_level",
        },
        "camera_movement": "push_in",
        "lighting_mood": "warm",
        "composition": "rule_of_thirds",
    }


def test_get_limit_returns_20_for_short_duration():
    assert get_narration_char_limit(2.0) == 20


def test_get_limit_returns_30_for_medium_short():
    assert get_narration_char_limit(3.5) == 30


def test_get_limit_returns_40_for_5s_archetype():
    assert get_narration_char_limit(5.0) == 40


def test_get_limit_returns_60_for_long_medium():
    assert get_narration_char_limit(8.0) == 60


def test_get_limit_returns_82_for_10s_archetype():
    assert get_narration_char_limit(10.0) == 82


def test_get_limit_returns_82_for_15s_max():
    assert get_narration_char_limit(15.0) == 82


def test_get_limit_boundary_edge_45_picks_30_not_40():
    assert get_narration_char_limit(4.5) == 30


def test_get_limit_boundary_edge_75_picks_40_not_60():
    assert get_narration_char_limit(7.5) == 40


def test_sceneshot_passes_with_narration_within_limit():
    shot = SceneShot(**valid_shot_dict(duration=5, narration="科技带来便利"))

    assert shot.narration_segment == "科技带来便利"


def test_sceneshot_rejects_narration_above_limit_for_5s():
    with pytest.raises(ValidationError, match="超过 5.0s 片段上限 40 字"):
        SceneShot(**valid_shot_dict(duration=5, narration="字" * 50))


def test_sceneshot_rejects_narration_above_limit_for_10s():
    with pytest.raises(ValidationError, match="超过 10.0s 片段上限 82 字"):
        SceneShot(**valid_shot_dict(duration=10, narration="字" * 100))


def test_sceneshot_accepts_82_chars_for_10s_boundary():
    shot = SceneShot(**valid_shot_dict(duration=10, narration="字" * 82))

    assert len(shot.narration_segment) == 82


def test_sceneshot_strips_whitespace_before_counting():
    shot = SceneShot(**valid_shot_dict(duration=5, narration=(" " * 90) + "短文本" + (" " * 90)))

    assert shot.narration_segment.strip() == "短文本"


def test_creative_prompt_contains_narration_length_constraint():
    style = StyleTemplate(
        name="test",
        display_name="测试风格",
        core_concept="短视频",
        visual_style="真实",
        caption_style="minimal",
        hook_rule="前三秒给出钩子",
        video_spec="15-30秒，9:16竖版",
    )

    prompt = _build_creative_system_prompt(style)

    assert "旁白字数硬约束" in prompt
    assert "最多 40 字" in prompt
    assert "最多 82 字" in prompt
    assert "len(narration_segment)" in prompt


def test_chains_v2_module_exports_unchanged():
    from layers.L2_creative.chains_v2 import lobster_creative_v2, lobster_evaluate_v2
    from layers.L2_creative.schemas import SchemaValidationError

    assert callable(lobster_creative_v2)
    assert callable(lobster_evaluate_v2)
    assert issubclass(SchemaValidationError, Exception)
