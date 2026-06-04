from __future__ import annotations

import pytest

from config.settings import Settings
from layers.L4_audio.visual_planner import (
    CHINESE_CHARS_PER_SEC,
    ClipPlan,
    NarrationTooLongError,
    estimate_narration_audio_sec,
    format_plan_for_feishu,
    pick_video_duration,
    plan_clip_durations,
)


def test_estimate_empty_returns_zero():
    assert estimate_narration_audio_sec("") == 0.0


def test_estimate_75_chars_at_default_rate_is_10s():
    assert estimate_narration_audio_sec("字" * 75) == pytest.approx(10.0)


def test_estimate_with_speed_factor_15_is_faster():
    assert estimate_narration_audio_sec("字" * 75, speed_factor=1.5) == pytest.approx(6.67, abs=0.01)


def test_estimate_strips_whitespace():
    assert estimate_narration_audio_sec("  1234567890  ") == pytest.approx(10 / CHINESE_CHARS_PER_SEC)


def test_estimate_includes_punctuation_in_count():
    assert estimate_narration_audio_sec("你好，世界！") == pytest.approx(6 / CHINESE_CHARS_PER_SEC)


def test_pick_5s_for_audio_below_46():
    assert pick_video_duration(4.5) == (5, False)


def test_pick_10s_for_audio_between_46_and_93():
    assert pick_video_duration(6.0) == (10, False)


def test_pick_10s_fallback_when_audio_above_93_returns_is_fallback_true():
    assert pick_video_duration(12.0) == (10, True)


def test_pick_strict_mode_raises_narration_too_long_error_above_93():
    with pytest.raises(NarrationTooLongError):
        pick_video_duration(12.0, strict=True)


def test_pick_boundary_46_picks_5s_not_10():
    assert pick_video_duration(4.6) == (5, False)


def test_pick_boundary_93_picks_10s_not_fallback():
    assert pick_video_duration(9.3) == (10, False)


def test_plan_returns_one_clipplan_per_input():
    plans = plan_clip_durations([
        {"clip_no": 1, "narration_segment": "短文本"},
        {"clip_no": 2, "narration_segment": "字" * 50},
    ])

    assert len(plans) == 2
    assert all(isinstance(p, ClipPlan) for p in plans)


def test_plan_handles_missing_narration_segment_as_empty():
    plans = plan_clip_durations([{"clip_no": 1}])

    assert plans[0].narration == ""
    assert plans[0].est_audio_sec == 0.0
    assert plans[0].target_video_sec == 5


def test_plan_writes_clip_no_from_input():
    plans = plan_clip_durations([{"clip_no": 9, "narration_segment": "短文本"}])

    assert plans[0].clip_no == 9


def test_plan_does_not_mutate_input_clips():
    clips = [{"clip_no": 1, "duration_sec": 5, "narration_segment": "字" * 50}]
    before = [dict(c) for c in clips]

    plan_clip_durations(clips)

    assert clips == before


def test_plan_strict_propagates_narration_too_long_error():
    with pytest.raises(NarrationTooLongError) as exc:
        plan_clip_durations([{"clip_no": 1, "narration_segment": "字" * 80}], strict=True)

    assert exc.value.narration == "字" * 80


def test_format_includes_emoji_header_and_clip_lines():
    msg = format_plan_for_feishu([
        ClipPlan(clip_no=1, narration="短文本", char_count=3, est_audio_sec=0.4, target_video_sec=5)
    ])

    assert "📐 P3 时长规划" in msg
    assert "clip 1" in msg
    assert "选 5s 视频" in msg


def test_format_marks_fallback_with_warning_icon():
    msg = format_plan_for_feishu([
        ClipPlan(
            clip_no=1,
            narration="字" * 80,
            char_count=80,
            est_audio_sec=10.67,
            target_video_sec=10,
            is_fallback=True,
        )
    ])

    assert "⚠️兜底" in msg


def test_settings_use_legacy_av_pipeline_default_false():
    assert Settings().use_legacy_av_pipeline is False


def test_settings_use_legacy_av_pipeline_env_override(monkeypatch):
    monkeypatch.setenv("USE_LEGACY_AV_PIPELINE", "true")

    assert Settings().use_legacy_av_pipeline is True
