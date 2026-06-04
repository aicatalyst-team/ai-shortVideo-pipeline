from __future__ import annotations

from types import SimpleNamespace

import pytest

from layers.L3_visual import clip_consistency
from layers.L3_visual.clip_consistency import (
    ClipConsistencyResult,
    check_consistency,
    score_image_prompt,
)
from layers.L3_visual.providers.base import ImageResult
from layers.L3_visual import text_to_image


@pytest.mark.asyncio
async def test_score_image_prompt_returns_none_when_model_load_fails(monkeypatch):
    async def fake_load() -> bool:
        return False

    monkeypatch.setattr(clip_consistency, "_ensure_model_loaded", fake_load)
    assert await score_image_prompt("x.png", "prompt") is None


@pytest.mark.asyncio
async def test_score_image_prompt_returns_none_when_inference_raises(monkeypatch):
    async def fake_load() -> bool:
        return True

    def boom(*_args, **_kwargs):
        raise RuntimeError("inference exploded")

    monkeypatch.setattr(clip_consistency, "_ensure_model_loaded", fake_load)
    monkeypatch.setattr(clip_consistency, "_score_sync", boom)

    assert await score_image_prompt("x.png", "prompt") is None


@pytest.mark.asyncio
async def test_check_consistency_returns_full_result_when_passed(monkeypatch):
    async def fake_score(_image_path: str, _prompt: str) -> float:
        return 0.5

    monkeypatch.setattr(clip_consistency, "score_image_prompt", fake_score)

    result = await check_consistency(
        "x.png",
        "red dress protagonist",
        threshold=0.22,
        storyboard_id="SB001",
        clip_no=2,
    )

    assert isinstance(result, ClipConsistencyResult)
    assert result.score == 0.5
    assert result.threshold == 0.22
    assert result.passed is True
    assert result.warning_message == ""


@pytest.mark.asyncio
async def test_check_consistency_warns_when_score_below_threshold(monkeypatch):
    async def fake_score(_image_path: str, _prompt: str) -> float:
        return 0.1

    monkeypatch.setattr(clip_consistency, "score_image_prompt", fake_score)

    result = await check_consistency("x.png", "prompt", threshold=0.22, clip_no=3)

    assert result.passed is False
    assert result.warning_message
    assert "0.100" in result.warning_message
    assert "第 3 段" in result.warning_message


@pytest.mark.asyncio
async def test_check_consistency_score_none_passes_without_warning(monkeypatch):
    async def fake_score(_image_path: str, _prompt: str) -> None:
        return None

    monkeypatch.setattr(clip_consistency, "score_image_prompt", fake_score)

    result = await check_consistency("x.png", "prompt", threshold=0.22)

    assert result.score is None
    assert result.passed is True
    assert result.warning_message == ""


@pytest.mark.asyncio
async def test_check_consistency_threshold_arg_overrides_settings(monkeypatch):
    async def fake_score(_image_path: str, _prompt: str) -> float:
        return 0.4

    monkeypatch.setattr(clip_consistency, "score_image_prompt", fake_score)

    result = await check_consistency("x.png", "prompt", threshold=0.7)

    assert result.threshold == 0.7
    assert result.passed is False


@pytest.mark.asyncio
async def test_attach_clip_consistency_skips_when_setting_disabled(monkeypatch):
    called = False

    async def fake_check(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        text_to_image,
        "get_settings",
        lambda: SimpleNamespace(clip_consistency_enabled=False),
    )
    monkeypatch.setattr(clip_consistency, "check_consistency", fake_check)

    result = ImageResult(url="https://example.test/img.png", local_path="x.png")
    out = await text_to_image._attach_clip_consistency(
        result,
        image_path="x.png",
        prompt="prompt",
        storyboard_id="SB001",
        clip_no=1,
    )

    assert out is result
    assert called is False
    assert out.clip_score is None
    assert out.clip_passed is True
    assert out.clip_warning == ""


@pytest.mark.asyncio
async def test_attach_clip_consistency_adds_warning_metadata(monkeypatch):
    async def fake_check(*_args, **_kwargs):
        return ClipConsistencyResult(
            image_path="x.png",
            prompt="prompt",
            score=0.1,
            threshold=0.22,
            passed=False,
            warning_message="warning",
        )

    monkeypatch.setattr(
        text_to_image,
        "get_settings",
        lambda: SimpleNamespace(clip_consistency_enabled=True),
    )
    monkeypatch.setattr(clip_consistency, "check_consistency", fake_check)

    result = ImageResult(url="https://example.test/img.png", local_path="x.png")
    out = await text_to_image._attach_clip_consistency(result, image_path="x.png", prompt="prompt")

    assert out.clip_score == 0.1
    assert out.clip_passed is False
    assert out.clip_warning == "warning"
