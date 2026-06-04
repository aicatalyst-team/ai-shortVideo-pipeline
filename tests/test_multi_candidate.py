from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from layers.L3_visual.providers.base import ImageResult
from layers.L3_visual.text_to_image import generate_with_candidates


def _image(path: str) -> ImageResult:
    return ImageResult(url=f"http://local/{path}", local_path=path, width=512, height=910, model="mock")


@pytest.mark.asyncio
async def test_generates_n_candidates_concurrently(tmp_path):
    active = 0
    max_active = 0

    async def fake_generate(**kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return _image(kwargs["output_path"])

    with patch("layers.L3_visual.text_to_image.generate_image", new=AsyncMock(side_effect=fake_generate)):
        results = await generate_with_candidates("coffee prompt", str(tmp_path), n=3)

    assert len(results) == 3
    assert max_active > 1


@pytest.mark.asyncio
async def test_partial_failure_returns_remaining(tmp_path):
    async def fake_generate(**kwargs):
        if kwargs["output_path"].endswith("01.png"):
            raise RuntimeError("bad candidate")
        return _image(kwargs["output_path"])

    with patch("layers.L3_visual.text_to_image.generate_image", new=AsyncMock(side_effect=fake_generate)):
        results = await generate_with_candidates("coffee prompt", str(tmp_path), n=3)

    assert len(results) == 2


@pytest.mark.asyncio
async def test_all_failure_returns_empty_list(tmp_path):
    with patch("layers.L3_visual.text_to_image.generate_image", new=AsyncMock(side_effect=RuntimeError("boom"))):
        results = await generate_with_candidates("coffee prompt", str(tmp_path), n=3)

    assert results == []


@pytest.mark.asyncio
async def test_each_candidate_uses_different_prompt_variation(tmp_path):
    prompts: list[str] = []

    async def fake_generate(**kwargs):
        prompts.append(kwargs["prompt"])
        return _image(kwargs["output_path"])

    with patch("layers.L3_visual.text_to_image.generate_image", new=AsyncMock(side_effect=fake_generate)):
        await generate_with_candidates("coffee prompt", str(tmp_path), n=3)

    assert prompts[0] == "coffee prompt"
    assert "subtle variation" in prompts[1]
    assert "alternative angle perspective" in prompts[2]
