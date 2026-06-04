from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.anyio
async def test_generate_image_truncates_prompt_before_submit(monkeypatch, tmp_path):
    import layers.L3_visual.text_to_image as module

    captured = {}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            captured["prompt"] = json["prompt"]
            return MagicMock(
                status_code=200,
                text='{"code":0,"data":{"task_id":"T1"}}',
                json=lambda: {"code": 0, "data": {"task_id": "T1"}},
            )

        async def get(self, url, headers=None):
            if url.endswith("/T1"):
                return MagicMock(
                    json=lambda: {
                        "data": {
                            "task_status": "succeed",
                            "task_result": {"images": [{"url": "http://img", "width": 512, "height": 512}]},
                        }
                    }
                )
            return MagicMock(content=b"png")

    monkeypatch.setattr(module.httpx, "AsyncClient", lambda timeout=300: _FakeClient())
    monkeypatch.setattr(
        "layers.L3_visual.providers.kling_v3.kling_image_headers",
        lambda: {"Authorization": "Bearer x"},
    )

    long_prompt = "x" * (module.IMAGE_PROMPT_MAX_LEN + 200)
    out = tmp_path / "img.png"

    result = await module.generate_image(prompt=long_prompt, output_path=str(out))

    assert len(captured["prompt"]) <= module.IMAGE_PROMPT_MAX_LEN
    assert result.local_path == str(out)
