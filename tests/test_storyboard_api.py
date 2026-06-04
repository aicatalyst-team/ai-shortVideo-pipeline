from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.storyboard_api import _STORYBOARD_STORE, register_storyboard, router
from layers.L2_creative.schemas import Storyboard
from layers.L2_creative.storyboard_engine import ThumbnailBatchResult, ThumbnailResult
from layers.L3_visual.providers.base import ImageResult


def _storyboard() -> Storyboard:
    return Storyboard(
        plan_id="P_API",
        title="coffee price rise",
        theme="coffee price rise affects young people",
        style_name="hot_news_commentary",
        main_character_id="su_wan",
        total_duration_sec=10,
        shots=[
            {
                "scene_no": 1,
                "narration_segment": "Coffee prices are rising.",
                "estimated_duration_sec": 5,
                "character_id": "su_wan",
                "environment_id": "coffee_shop",
                "time_of_day": "morning",
                "subject_action": "looking at receipt",
                "subject_emotion": "surprised",
                "lighting_mood": "warm",
            },
            {
                "scene_no": 2,
                "narration_segment": "Extreme weather is the hidden cause.",
                "estimated_duration_sec": 5,
                "character_id": "su_wan",
                "environment_id": "coffee_shop",
                "time_of_day": "morning",
                "subject_action": "thinking deeply",
                "subject_emotion": "thinking",
                "lighting_mood": "warm",
            },
        ],
    )


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _result_with_scalar(value):
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    return result


def _result_with_all(values):
    result = MagicMock()
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=values)))
    return result


def _patch_db_results(monkeypatch, results):
    fake_session = MagicMock()
    fake_session.execute = AsyncMock(side_effect=results)
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)
    fake_factory = MagicMock(return_value=fake_session)
    monkeypatch.setattr("api.storyboard_api.get_session_factory", lambda: fake_factory)
    return fake_session


def setup_function():
    _STORYBOARD_STORE.clear()


def test_get_storyboard_not_found(monkeypatch):
    _patch_db_results(monkeypatch, [_result_with_scalar(None)])

    resp = _client().get("/api/v1/storyboards/not-found")

    assert resp.status_code == 404


def test_get_storyboard_returns_registered_after_db_miss(monkeypatch):
    _patch_db_results(monkeypatch, [_result_with_scalar(None)])
    register_storyboard(_storyboard())

    resp = _client().get("/api/v1/storyboards/P_API")

    assert resp.status_code == 200
    body = resp.json()
    assert body["plan_id"] == "P_API"
    assert body["source"] == "in-memory"
    assert len(body["clips"]) == 2
    assert body["clips"][0]["r_metadata"]["scene_no"] == 1


def test_preview_storyboard_returns_thumbnails():
    register_storyboard(_storyboard())
    batch = ThumbnailBatchResult(
        plan_id="P_API",
        total=2,
        succeeded=2,
        failed=0,
        items=[
            ThumbnailResult(1, True, ImageResult(url="http://img/1.png"), "p1", "", 10),
            ThumbnailResult(2, True, ImageResult(url="http://img/2.png"), "p2", "", 12),
        ],
    )

    with patch("api.storyboard_api.generate_storyboard_thumbnails", new=AsyncMock(return_value=batch)):
        resp = _client().post("/api/v1/storyboards/P_API/preview")

    assert resp.status_code == 200
    body = resp.json()
    assert body["succeeded"] == 2
    assert len(body["thumbnails"]) == 2
    assert body["thumbnails"][0]["image_url"] == "http://img/1.png"


def test_preview_storyboard_partial_failure():
    register_storyboard(_storyboard())
    batch = ThumbnailBatchResult(
        plan_id="P_API",
        total=2,
        succeeded=1,
        failed=1,
        items=[
            ThumbnailResult(1, True, ImageResult(url="http://img/1.png"), "p1", "", 10),
            ThumbnailResult(2, False, None, "p2", "failed", 12),
        ],
    )

    with patch("api.storyboard_api.generate_storyboard_thumbnails", new=AsyncMock(return_value=batch)):
        resp = _client().post("/api/v1/storyboards/P_API/preview")

    assert resp.status_code == 200
    body = resp.json()
    assert body["succeeded"] == 1
    assert body["failed"] == 1
    assert body["thumbnails"][1]["error"] == "failed"


def test_get_storyboard_from_db(monkeypatch):
    fake_sb = MagicMock(
        id="SB123",
        plan_id="P001",
        title="db storyboard",
        theme="theme",
        style_name="hot_news_commentary",
        status="ready",
        storyboard_metadata={"backfilled": True},
    )
    fake_clip = MagicMock(
        id="C1",
        seq=1,
        prompt="p",
        narration_segment="n",
        duration_sec=5,
        video_url="",
        status="ready",
        r_metadata={"k": "v"},
    )
    _patch_db_results(monkeypatch, [_result_with_scalar(fake_sb), _result_with_all([fake_clip])])

    resp = _client().get("/api/v1/storyboards/P001")

    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "db"
    assert body["id"] == "SB123"
    assert body["metadata"]["backfilled"] is True
    assert body["clips"][0]["id"] == "C1"
    assert body["clips"][0]["r_metadata"]["k"] == "v"
    assert body["frames"] == []


def test_get_storyboard_from_db_includes_frames(monkeypatch):
    fake_sb = MagicMock(
        id="SB123",
        plan_id="P001",
        title="db storyboard",
        theme="theme",
        style_name="hot_news_commentary",
        status="ready",
        storyboard_metadata=None,
    )
    fake_clip = MagicMock(
        id="C1",
        seq=1,
        prompt="p",
        narration_segment="n",
        duration_sec=5,
        video_url="",
        status="ready",
        r_metadata=None,
    )
    fake_frame = MagicMock(id="F1", clip_id="C1", kind="first", url="http://img", width=512, height=910)
    fake_session = _patch_db_results(
        monkeypatch,
        [_result_with_scalar(fake_sb), _result_with_all([fake_clip]), _result_with_all([fake_frame])],
    )

    resp = _client().get("/api/v1/storyboards/P001?include_frames=true")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["frames"]) == 1
    assert body["frames"][0]["kind"] == "first"
    assert fake_session.execute.await_count == 3


def test_clip_response_model_serializes():
    from api.storyboard_api import ClipResponse

    c = ClipResponse(
        id="C1",
        seq=1,
        prompt="p",
        narration_segment="n",
        duration_sec=5,
        video_url="",
        status="ready",
        r_metadata={"k": "v"},
    )

    dumped = c.model_dump()
    assert dumped["id"] == "C1"
    assert dumped["r_metadata"]["k"] == "v"


def test_frame_asset_response_model_serializes():
    from api.storyboard_api import FrameAssetResponse

    frame = FrameAssetResponse(id="F1", clip_id="C1", kind="first", url="http://x", width=512, height=910)

    assert frame.kind == "first"


def test_storyboard_db_response_model_with_clips_and_frames():
    from api.storyboard_api import ClipResponse, FrameAssetResponse, StoryboardDbResponse

    sb = StoryboardDbResponse(
        id="SB1",
        plan_id="P1",
        title="t",
        theme="th",
        style_name="hot_news_commentary",
        status="ready",
        metadata=None,
        clips=[
            ClipResponse(
                id="C1",
                seq=1,
                prompt="",
                narration_segment="",
                duration_sec=5,
                video_url="",
                status="ready",
            ),
        ],
        frames=[
            FrameAssetResponse(id="F1", clip_id="C1", kind="first", url="", width=0, height=0),
        ],
        source="db",
    )

    assert sb.source == "db"
    assert len(sb.clips) == 1
    assert len(sb.frames) == 1
