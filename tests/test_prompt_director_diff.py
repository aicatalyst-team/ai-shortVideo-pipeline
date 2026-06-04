from __future__ import annotations

import logging

from layers.L2_creative.creative_skills import get_creative_skill
from layers.L2_creative.prompt_director import (
    build_user_intent,
    compile_prompt_director_plan,
    list_supported_hints,
    prompt_diff_for_regenerate,
)


def _base_plan():
    skill = get_creative_skill("电影")
    assert skill is not None
    intent = build_user_intent(
        "做一条 AI 编程效率短片",
        skill,
        {
            "audience_emotion": "被震撼",
            "subject_profile": "创业者/技术人",
            "style_intensity": "标准增强",
        },
    )
    return compile_prompt_director_plan(intent, narration_segment="他把重复工作交给 Agent")


def test_closer_shot_changes_shot_type_only():
    plan = _base_plan()
    patched = prompt_diff_for_regenerate(plan, ["closer_shot"])

    assert patched.shot_plan.shot_type == "close_up"
    assert patched.shot_plan.lighting == plan.shot_plan.lighting
    assert patched.shot_plan.scene_texture == plan.shot_plan.scene_texture
    assert patched.model_prompt == plan.model_prompt


def test_wider_shot_changes_shot_type():
    patched = prompt_diff_for_regenerate(_base_plan(), ["wider_shot"])

    assert patched.shot_plan.shot_type == "wide_shot"


def test_no_text_strengthens_negative_prompt():
    plan = _base_plan()
    patched = prompt_diff_for_regenerate(plan, ["no_text"])

    assert patched.model_prompt.negative_prompt.startswith("绝对不要任何文字")
    assert "绝对不要乱码" in patched.model_prompt.negative_prompt
    assert patched.model_prompt.negative_prompt.endswith(plan.model_prompt.negative_prompt)
    assert patched.shot_plan == plan.shot_plan


def test_more_realistic_appends_to_scene_texture():
    plan = _base_plan()
    patched = prompt_diff_for_regenerate(plan, ["more_realistic"])

    assert patched.shot_plan.scene_texture.startswith(plan.shot_plan.scene_texture)
    assert "documentary-like" in patched.shot_plan.scene_texture
    assert patched.shot_plan.lighting == plan.shot_plan.lighting


def test_more_dramatic_modifies_both_scene_and_lighting():
    patched = prompt_diff_for_regenerate(_base_plan(), ["more_dramatic"])

    assert "dramatic mood" in patched.shot_plan.scene_texture
    assert "more dramatic chiaroscuro" in patched.shot_plan.lighting


def test_brighter_appends_to_lighting():
    patched = prompt_diff_for_regenerate(_base_plan(), ["brighter"])

    assert "brighter exposure" in patched.shot_plan.lighting


def test_darker_appends_to_lighting():
    patched = prompt_diff_for_regenerate(_base_plan(), ["darker"])

    assert "low-key moody lighting" in patched.shot_plan.lighting


def test_warmer_tone_appends_to_lighting():
    patched = prompt_diff_for_regenerate(_base_plan(), ["warmer_tone"])

    assert "warm color tone" in patched.shot_plan.lighting


def test_cooler_tone_appends_to_lighting():
    patched = prompt_diff_for_regenerate(_base_plan(), ["cooler_tone"])

    assert "cool blue color tone" in patched.shot_plan.lighting


def test_more_motion_appends_to_camera_motion():
    patched = prompt_diff_for_regenerate(_base_plan(), ["more_motion"])

    assert "more pronounced but still stable movement" in patched.shot_plan.camera_motion


def test_static_shot_forces_camera_motion():
    patched = prompt_diff_for_regenerate(_base_plan(), ["static_shot"])

    assert patched.shot_plan.camera_motion == "fully static camera, no movement at all"


def test_different_character_only_writes_note(caplog):
    plan = _base_plan()

    with caplog.at_level(logging.WARNING):
        patched = prompt_diff_for_regenerate(plan, ["different_character"])

    assert patched.shot_plan == plan.shot_plan
    assert patched.model_prompt == plan.model_prompt
    assert "用户想换主角" in patched.user_intent.custom_notes[-1]
    assert "different_character" in caplog.text


def test_different_scene_modifies_scene_and_writes_note(caplog):
    plan = _base_plan()

    with caplog.at_level(logging.WARNING):
        patched = prompt_diff_for_regenerate(plan, ["different_scene"])

    assert patched.shot_plan.scene_texture.startswith(plan.shot_plan.scene_texture)
    assert "alternative scene setting" in patched.shot_plan.scene_texture
    assert "用户想换场景" in patched.user_intent.custom_notes[-1]
    assert "different_scene" in caplog.text


def test_multiple_hints_apply_in_order():
    patched = prompt_diff_for_regenerate(_base_plan(), ["more_motion", "static_shot"])

    assert patched.shot_plan.camera_motion == "fully static camera, no movement at all"


def test_closer_shot_plus_no_text_independent_fields():
    plan = _base_plan()
    patched = prompt_diff_for_regenerate(plan, ["closer_shot", "no_text"])

    assert patched.shot_plan.shot_type == "close_up"
    assert patched.model_prompt.negative_prompt.startswith("绝对不要任何文字")
    assert patched.shot_plan.lighting == plan.shot_plan.lighting


def test_empty_hints_returns_unchanged_plan_copy():
    plan = _base_plan()
    patched = prompt_diff_for_regenerate(plan, [])

    assert patched == plan
    assert patched is not plan
    assert patched.shot_plan is not plan.shot_plan


def test_unknown_hint_skipped_silently(caplog):
    plan = _base_plan()

    with caplog.at_level(logging.WARNING):
        patched = prompt_diff_for_regenerate(plan, ["mystery_hint"])

    assert patched == plan
    assert "mystery_hint" in caplog.text


def test_input_plan_not_mutated():
    plan = _base_plan()
    original_type = plan.shot_plan.shot_type
    original_negative = plan.model_prompt.negative_prompt

    patched = prompt_diff_for_regenerate(plan, ["closer_shot", "no_text"])

    assert plan.shot_plan.shot_type == original_type
    assert plan.model_prompt.negative_prompt == original_negative
    assert patched.shot_plan.shot_type != original_type


def test_custom_notes_appended_to_user_intent():
    patched = prompt_diff_for_regenerate(_base_plan(), [], custom_notes=["希望更像纪录片"])

    assert "希望更像纪录片" in patched.user_intent.custom_notes


def test_custom_notes_dedupe():
    plan = _base_plan()
    plan.user_intent.custom_notes.append("希望更像纪录片")

    patched = prompt_diff_for_regenerate(
        plan,
        [],
        custom_notes=["希望更像纪录片", "不要油腻"],
    )

    assert patched.user_intent.custom_notes.count("希望更像纪录片") == 1
    assert "不要油腻" in patched.user_intent.custom_notes


def test_list_supported_hints_returns_all_13():
    assert list_supported_hints() == sorted(
        [
            "closer_shot",
            "wider_shot",
            "more_realistic",
            "more_dramatic",
            "no_text",
            "brighter",
            "darker",
            "warmer_tone",
            "cooler_tone",
            "more_motion",
            "static_shot",
            "different_character",
            "different_scene",
        ]
    )
