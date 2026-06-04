from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from layers.L2_creative.schemas import Storyboard
from layers.L2_creative.storyboard_engine import _build_thumbnail_prompt, generate_storyboard_thumbnails
from layers.L3_visual.providers.base import ImageResult


def _storyboard(num_shots: int = 3) -> Storyboard:
    shots = []
    for i in range(1, num_shots + 1):
        shots.append(
            {
                "scene_no": i,
                "narration_segment": f"第 {i} 段咖啡涨价旁白。",
                "estimated_duration_sec": 5,
                "character_id": "su_wan",
                "environment_id": "coffee_shop",
                "time_of_day": "morning",
                "subject_action": "looking at receipt",
                "subject_emotion": "surprised",
                "key_props": ["coffee cup", "receipt"],
                "lighting_mood": "warm",
            }
        )
    return Storyboard(
        plan_id="P_THUMB",
        title="咖啡涨价",
        theme="咖啡涨价影响年轻人",
        style_name="hot_news_commentary",
        main_character_id="su_wan",
        total_duration_sec=5 * num_shots,
        shots=shots,
    )


def _image(path: str) -> ImageResult:
    return ImageResult(url=f"http://local/{path}", local_path=path, width=256, height=455, model="mock")


@pytest.mark.asyncio
async def test_thumbnail_batch_success(tmp_path):
    async_mock = AsyncMock(side_effect=lambda **kwargs: _image(kwargs["output_path"]))
    with patch("layers.L3_visual.text_to_image.generate_image", new=async_mock):
        result = await generate_storyboard_thumbnails(_storyboard(3), tmp_path)

    assert result.total == 3
    assert result.succeeded == 3
    assert result.failed == 0
    assert [item.scene_no for item in result.items] == [1, 2, 3]


@pytest.mark.asyncio
async def test_thumbnail_batch_partial_failure(tmp_path):
    async def fake_generate(**kwargs):
        if kwargs["output_path"].endswith("02.png"):
            raise RuntimeError("bad image")
        return _image(kwargs["output_path"])

    with patch("layers.L3_visual.text_to_image.generate_image", new=AsyncMock(side_effect=fake_generate)):
        result = await generate_storyboard_thumbnails(_storyboard(3), tmp_path)

    assert result.succeeded == 2
    assert result.failed == 1
    assert result.items[1].success is False
    assert "bad image" in result.items[1].error


@pytest.mark.asyncio
async def test_thumbnail_batch_respects_concurrency_limit(tmp_path):
    order: list[str] = []

    async def fake_generate(**kwargs):
        order.append(f"start:{kwargs['output_path']}")
        await asyncio.sleep(0.01)
        order.append(f"end:{kwargs['output_path']}")
        return _image(kwargs["output_path"])

    with patch("layers.L3_visual.text_to_image.generate_image", new=AsyncMock(side_effect=fake_generate)):
        await generate_storyboard_thumbnails(_storyboard(3), tmp_path, max_concurrency=1)

    assert order[0].startswith("start:")
    assert order[1].startswith("end:")
    assert order[2].startswith("start:")


@pytest.mark.asyncio
async def test_thumbnail_batch_timeout(tmp_path):
    async def hanging_generate(**kwargs):
        await asyncio.sleep(0.1)
        return _image(kwargs["output_path"])

    with patch("layers.L3_visual.text_to_image.generate_image", new=AsyncMock(side_effect=hanging_generate)):
        result = await generate_storyboard_thumbnails(_storyboard(1), tmp_path, timeout_per_shot=0.01)

    assert result.succeeded == 0
    assert result.failed == 1
    assert "timeout" in result.items[0].error


def test_thumbnail_prompt_contains_world_refs():
    shot = _storyboard(1).shots[0]

    prompt = _build_thumbnail_prompt(shot)

    assert "young Chinese woman" in prompt
    assert "咖啡馆" in prompt
    assert "medium shot" in prompt


# ── R5 改 30%: thumbnail 也接入 negative_prompt ──


@pytest.mark.asyncio
async def test_thumbnail_passes_negative_prompt_to_generate_image(tmp_path):
    """thumbnail 生成时必须传 negative_prompt（）。"""
    captured_kwargs = []

    async def _capture(**kwargs):
        captured_kwargs.append(kwargs)
        return _image(kwargs["output_path"])

    with patch("layers.L3_visual.text_to_image.generate_image", new=AsyncMock(side_effect=_capture)):
        await generate_storyboard_thumbnails(_storyboard(2), tmp_path)

    assert len(captured_kwargs) == 2
    for kw in captured_kwargs:
        # 必须传 negative_prompt
        assert "negative_prompt" in kw
        negative = kw["negative_prompt"]
        # 应包含基础质量负面词
        assert "low quality" in negative
        # warm lighting → negative 含 cold/harsh
        assert "cold blue" in negative or "harsh shadows" in negative
