from __future__ import annotations

import pytest

from layers.L4_audio.cost_estimator import estimate_clip_cost, estimate_clips_total_cost


def test_estimate_5s_standard_kling_v2_5():
    assert estimate_clip_cost("kling-v2-5-turbo", 5, "standard") == 0.6


def test_estimate_10s_standard_kling_v2_5():
    assert estimate_clip_cost("kling-v2-5-turbo", 10, "standard") == 1.1


def test_estimate_pro_costs_more_than_standard():
    standard = estimate_clip_cost("kling-v2-5-turbo", 5, "standard")
    pro = estimate_clip_cost("kling-v2-5-turbo", 5, "pro")
    assert pro > standard


def test_estimate_unknown_model_falls_back_to_kling_v2_5():
    assert estimate_clip_cost("unknown-model", 5, "standard") == estimate_clip_cost(
        "kling-v2-5-turbo", 5, "standard"
    )


def test_estimate_no_first_frame_excludes_text_image_cost():
    with_frame = estimate_clip_cost("kling-v2-5-turbo", 5, "standard", include_first_frame=True)
    without_frame = estimate_clip_cost("kling-v2-5-turbo", 5, "standard", include_first_frame=False)
    assert with_frame - without_frame == pytest.approx(0.1)


def test_estimate_tts_cost_scales_with_chars():
    no_tts = estimate_clip_cost("kling-v2-5-turbo", 5, "standard", narration_char_count=0)
    with_tts = estimate_clip_cost("kling-v2-5-turbo", 5, "standard", narration_char_count=1000)
    assert with_tts - no_tts == pytest.approx(0.3)


def test_estimate_clips_total_sums_correctly():
    clips = [
        {"duration_sec": 5, "narration_segment": "字" * 35},
        {"duration_sec": 10, "narration_segment": "字" * 70},
    ]
    expected = round(
        estimate_clip_cost("kling-v2-5-turbo", 5, "standard", narration_char_count=35)
        + estimate_clip_cost("kling-v2-5-turbo", 10, "standard", narration_char_count=70),
        2,
    )
    assert estimate_clips_total_cost(clips) == expected


def test_estimate_clips_total_handles_missing_narration_segment():
    clips = [{"duration_sec": 5}]
    assert estimate_clips_total_cost(clips) == 0.6
