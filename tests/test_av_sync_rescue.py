from __future__ import annotations

import pytest

from layers.L5_postprod import av_sync_rescue as module
from layers.L5_postprod.av_sync_rescue import (
    RescueResult,
    RescueStrategy,
    _calc_atempo,
    attempt_rescue,
)


def test_calc_atempo_clips_large_ratio_to_max():
    assert _calc_atempo(video_sec=35, audio_sec=51) == pytest.approx(1.30)


def test_calc_atempo_stays_in_configured_range():
    assert 0.85 <= _calc_atempo(video_sec=100, audio_sec=10) <= 1.30
    assert 0.85 <= _calc_atempo(video_sec=10, audio_sec=100) <= 1.30


@pytest.mark.asyncio
async def test_attempt_rescue_drift_2s_uses_audio_tempo(monkeypatch):
    calls = []

    async def fake_audio_tempo(**kwargs):
        calls.append(kwargs["strategy"])
        return RescueResult(True, RescueStrategy.AUDIO_TEMPO, "rescued.mp4", 0.2)

    monkeypatch.setattr(module, "_try_audio_tempo", fake_audio_tempo)

    result = await attempt_rescue(
        mixed_path="mixed.mp4",
        video_path="video.mp4",
        voiceover_path="voice.mp3",
        narration_text="hello",
        drift_sec=2.0,
        output_dir="out",
    )

    assert result.success is True
    assert result.strategy == RescueStrategy.AUDIO_TEMPO
    assert calls == [RescueStrategy.AUDIO_TEMPO]


@pytest.mark.asyncio
async def test_attempt_rescue_drift_5s_uses_audio_pad(monkeypatch):
    async def fake_audio_pad(**_kwargs):
        return RescueResult(True, RescueStrategy.AUDIO_TEMPO_VIDEO_PAD, "rescued.mp4", 0.3)

    monkeypatch.setattr(module, "_try_audio_pad", fake_audio_pad)

    result = await attempt_rescue(
        mixed_path="mixed.mp4",
        video_path="video.mp4",
        voiceover_path="voice.mp3",
        narration_text="hello",
        drift_sec=5.0,
        output_dir="out",
    )

    assert result.success is True
    assert result.strategy == RescueStrategy.AUDIO_TEMPO_VIDEO_PAD


@pytest.mark.asyncio
async def test_attempt_rescue_drift_10s_uses_rewrite(monkeypatch):
    async def fake_rewrite(**_kwargs):
        return RescueResult(True, RescueStrategy.NARRATION_REWRITE, "rescued.mp4", 0.4, cost_cny=0.01)

    monkeypatch.setattr(module, "_try_rewrite", fake_rewrite)

    result = await attempt_rescue(
        mixed_path="mixed.mp4",
        video_path="video.mp4",
        voiceover_path="voice.mp3",
        narration_text="hello",
        drift_sec=10.0,
        output_dir="out",
    )

    assert result.success is True
    assert result.strategy == RescueStrategy.NARRATION_REWRITE


@pytest.mark.asyncio
async def test_attempt_rescue_drift_20s_hard_fails():
    result = await attempt_rescue(
        mixed_path="mixed.mp4",
        video_path="video.mp4",
        voiceover_path="voice.mp3",
        narration_text="hello",
        drift_sec=20.0,
        output_dir="out",
    )

    assert result.success is False
    assert result.strategy == RescueStrategy.HARD_FAIL


@pytest.mark.asyncio
async def test_attempt_rescue_ffmpeg_failure_returns_false(monkeypatch):
    async def fake_audio_tempo(**_kwargs):
        raise RuntimeError("ffmpeg failed")

    async def fake_audio_pad(**_kwargs):
        raise RuntimeError("pad failed")

    async def fake_rewrite(**_kwargs):
        raise RuntimeError("rewrite failed")

    monkeypatch.setattr(module, "_try_audio_tempo", fake_audio_tempo)
    monkeypatch.setattr(module, "_try_audio_pad", fake_audio_pad)
    monkeypatch.setattr(module, "_try_rewrite", fake_rewrite)

    result = await attempt_rescue(
        mixed_path="mixed.mp4",
        video_path="video.mp4",
        voiceover_path="voice.mp3",
        narration_text="hello",
        drift_sec=2.0,
        output_dir="out",
    )

    assert result.success is False
    assert result.strategy == RescueStrategy.HARD_FAIL
    assert "rewrite failed" in result.message


@pytest.mark.asyncio
async def test_attempt_rescue_failed_verification_returns_false(monkeypatch):
    async def fake_audio_tempo(**_kwargs):
        return RescueResult(False, RescueStrategy.AUDIO_TEMPO, None, None, message="still drift")

    async def fake_audio_pad(**_kwargs):
        return RescueResult(False, RescueStrategy.AUDIO_TEMPO_VIDEO_PAD, None, None, message="still drift")

    async def fake_rewrite(**_kwargs):
        return RescueResult(False, RescueStrategy.NARRATION_REWRITE, None, None, message="still drift")

    monkeypatch.setattr(module, "_try_audio_tempo", fake_audio_tempo)
    monkeypatch.setattr(module, "_try_audio_pad", fake_audio_pad)
    monkeypatch.setattr(module, "_try_rewrite", fake_rewrite)

    result = await attempt_rescue(
        mixed_path="mixed.mp4",
        video_path="video.mp4",
        voiceover_path="voice.mp3",
        narration_text="hello",
        drift_sec=2.0,
        output_dir="out",
    )

    assert result.success is False
    assert result.strategy == RescueStrategy.HARD_FAIL
    assert result.message == "still drift"
