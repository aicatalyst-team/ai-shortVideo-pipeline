from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from layers.L3_visual.providers import kling3
from layers.L3_visual.providers.kling3 import (
    KLING3_MAX_DURATION_SEC,
    KLING3_MIN_DURATION_SEC,
    Kling3FeatureUnsupportedError,
    Kling3NotAvailableError,
    Kling3Request,
    _clamp_duration,
    generate_native_audio_video,
    is_kling3_enabled,
)


class FakeResponse:
    def __init__(self, data=None, *, text: str = "", content: bytes = b"video"):
        self._data = data
        self.text = text
        self.content = content

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data

    def raise_for_status(self):
        return None


class FakeAsyncClient:
    def __init__(self, *, post_response=None, get_responses=None, post_exc=None, **kwargs):
        self.post_response = post_response
        self.get_responses = list(get_responses or [])
        self.post_exc = post_exc
        self.posts = []
        self.gets = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        if self.post_exc:
            raise self.post_exc
        return self.post_response

    async def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        if self.get_responses:
            return self.get_responses.pop(0)
        return FakeResponse({"data": {"task_status": "processing"}})


def _settings(mode: str = "stitched_i2v"):
    return SimpleNamespace(
        visual_generation_mode=mode,
        kling_base_url="https://kling.example",
        kling3_base_url="",
        kling_access_key="ak",
        kling_secret_key="sk",
        kling3_access_key="",
        kling3_secret_key="",
        kling3_model="kling-v3.0",
    )


@pytest.fixture(autouse=True)
def patch_common(monkeypatch):
    monkeypatch.setattr(kling3, "get_settings", lambda: _settings())
    monkeypatch.setattr(kling3, "kling3_headers", lambda: {"Authorization": "Bearer test"})

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(kling3.asyncio, "sleep", no_sleep)


def test_constants_in_expected_range():
    assert 3 <= KLING3_MIN_DURATION_SEC <= KLING3_MAX_DURATION_SEC <= 15


def test_clamp_below_min_returns_min():
    assert _clamp_duration(1) == 3


def test_clamp_above_max_returns_max():
    assert _clamp_duration(30) == 15


def test_clamp_within_range_passes_through():
    assert _clamp_duration(7) == 7


def test_clamp_handles_zero_or_none():
    assert _clamp_duration(0) == 5
    assert _clamp_duration(None) == 5


def test_request_dataclass_fields():
    req = Kling3Request(
        image_path="first.png",
        narration="旁白",
        visual_prompt="画面",
        duration_sec=5,
        character_ref_path="char.png",
    )
    assert req.image_path == "first.png"
    assert req.narration == "旁白"
    assert req.visual_prompt == "画面"
    assert req.duration_sec == 5
    assert req.character_ref_path == "char.png"


def test_request_default_enable_native_audio_true():
    req = Kling3Request(image_path=None, narration="旁白", visual_prompt="画面", duration_sec=5)
    assert req.enable_native_audio is True


def test_is_kling3_enabled_default_false(monkeypatch):
    monkeypatch.setattr(kling3, "get_settings", lambda: _settings("stitched_i2v"))
    assert is_kling3_enabled() is False


def test_is_kling3_enabled_true_when_mode_switched(monkeypatch):
    monkeypatch.setattr(kling3, "get_settings", lambda: _settings("kling3_native_audio"))
    assert is_kling3_enabled() is True


@pytest.mark.asyncio
async def test_generate_raises_not_available_on_http_error(monkeypatch, tmp_path):
    def client_factory(**kwargs):
        return FakeAsyncClient(post_exc=httpx.ConnectError("offline"))

    monkeypatch.setattr(kling3.httpx, "AsyncClient", client_factory)
    req = Kling3Request(image_path=None, narration="旁白", visual_prompt="画面", duration_sec=5)
    with pytest.raises(Kling3NotAvailableError):
        await generate_native_audio_video(req, output_path=str(tmp_path / "out.mp4"))


@pytest.mark.asyncio
async def test_generate_raises_feature_unsupported_when_audio_error_msg(monkeypatch, tmp_path):
    def client_factory(**kwargs):
        return FakeAsyncClient(
            post_response=FakeResponse({"code": 1201, "message": "native_audio not enabled"})
        )

    monkeypatch.setattr(kling3.httpx, "AsyncClient", client_factory)
    req = Kling3Request(image_path=None, narration="旁白", visual_prompt="画面", duration_sec=5)
    with pytest.raises(Kling3FeatureUnsupportedError):
        await generate_native_audio_video(req, output_path=str(tmp_path / "out.mp4"))


@pytest.mark.asyncio
async def test_generate_raises_runtime_on_non_zero_code(monkeypatch, tmp_path):
    def client_factory(**kwargs):
        return FakeAsyncClient(post_response=FakeResponse({"code": 999, "message": "bad"}))

    monkeypatch.setattr(kling3.httpx, "AsyncClient", client_factory)
    req = Kling3Request(image_path=None, narration="旁白", visual_prompt="画面", duration_sec=5)
    with pytest.raises(RuntimeError, match="submit failed"):
        await generate_native_audio_video(req, output_path=str(tmp_path / "out.mp4"))


@pytest.mark.asyncio
async def test_generate_raises_when_task_id_missing(monkeypatch, tmp_path):
    def client_factory(**kwargs):
        return FakeAsyncClient(post_response=FakeResponse({"code": 0, "data": {}}))

    monkeypatch.setattr(kling3.httpx, "AsyncClient", client_factory)
    req = Kling3Request(image_path=None, narration="旁白", visual_prompt="画面", duration_sec=5)
    with pytest.raises(Kling3NotAvailableError, match="missing task_id"):
        await generate_native_audio_video(req, output_path=str(tmp_path / "out.mp4"))


@pytest.mark.asyncio
async def test_generate_success_returns_kling3_result(monkeypatch, tmp_path):
    fake_client = FakeAsyncClient(
        post_response=FakeResponse({"code": 0, "data": {"task_id": "T123"}}),
        get_responses=[
            FakeResponse(
                {
                    "data": {
                        "task_status": "succeed",
                        "task_result": {
                            "videos": [
                                {
                                    "url": "https://cdn.example/video.mp4",
                                    "duration": 5,
                                    "has_audio": True,
                                    "audio_duration": 4.9,
                                }
                            ]
                        },
                    }
                }
            ),
            FakeResponse(content=b"mp4-bytes"),
        ],
    )
    monkeypatch.setattr(kling3.httpx, "AsyncClient", lambda **kwargs: fake_client)

    out = tmp_path / "out.mp4"
    req = Kling3Request(image_path=None, narration="旁白", visual_prompt="画面", duration_sec=5)
    result = await generate_native_audio_video(req, output_path=str(out))

    assert result.task_id == "T123"
    assert result.audio_included is True
    assert result.audio_duration_sec == 4.9
    assert result.video.local_path == str(out)
    assert out.read_bytes() == b"mp4-bytes"
    assert fake_client.posts[0][0].endswith("/v1/videos/text2video_v3")


@pytest.mark.asyncio
async def test_generate_timeout_raises_runtime(monkeypatch, tmp_path):
    def client_factory(**kwargs):
        return FakeAsyncClient(
            post_response=FakeResponse({"code": 0, "data": {"task_id": "T123"}}),
            get_responses=[
                FakeResponse({"data": {"task_status": "processing"}}),
                FakeResponse({"data": {"task_status": "processing"}}),
            ],
        )

    monkeypatch.setattr(kling3.httpx, "AsyncClient", client_factory)
    req = Kling3Request(image_path=None, narration="旁白", visual_prompt="画面", duration_sec=5)
    with pytest.raises(RuntimeError, match="task timeout"):
        await generate_native_audio_video(
            req,
            output_path=str(tmp_path / "out.mp4"),
            timeout_sec=2,
            poll_interval_sec=1,
        )
