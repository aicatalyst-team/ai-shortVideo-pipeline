from __future__ import annotations

import pytest

from core.scheduler import task_regenerate_clip
from layers.L3_visual.regenerate import ClipNotFoundError, RegenerateResult


@pytest.mark.asyncio
async def test_task_progresses_through_stages_on_success(monkeypatch):
    upsert_calls = []

    async def _record_upsert(job_id, **kwargs):
        upsert_calls.append(kwargs)

    fake_result = RegenerateResult(
        clip_id="C1",
        new_version=2,
        new_video_url="http://new.mp4",
        new_tail_frame_url="http://tail.png",
        dirty_clip_ids=["C2"],
        cost_cny=1.2,
        duration_ms=12000,
    )

    async def _fake_regen(*args, **kwargs):
        return fake_result

    monkeypatch.setattr("core.scheduler._upsert_job_status", _record_upsert)
    monkeypatch.setattr("layers.L3_visual.regenerate.regenerate_clip", _fake_regen)

    result = await task_regenerate_clip({"job_id": "J1"}, "C1", new_prompt="x")

    assert result["status"] == "done"
    assert result["clip_id"] == "C1"
    assert result["new_version"] == 2

    progress_seq = [
        c.get("progress") for c in upsert_calls if c.get("progress") is not None
    ]
    assert progress_seq == [5, 30, 90, 100]

    stages = [
        c.get("progress_stage")
        for c in upsert_calls
        if c.get("progress_stage") is not None
    ]
    assert "starting" in stages
    assert "generating_video" in stages
    assert "updating_db" in stages
    assert "done" in stages


@pytest.mark.asyncio
async def test_task_marks_failed_on_clip_not_found(monkeypatch):
    upsert_calls = []

    async def _record(job_id, **kwargs):
        upsert_calls.append(kwargs)

    async def _fake_regen(*args, **kwargs):
        raise ClipNotFoundError("NOPE")

    monkeypatch.setattr("core.scheduler._upsert_job_status", _record)
    monkeypatch.setattr("layers.L3_visual.regenerate.regenerate_clip", _fake_regen)

    with pytest.raises(ClipNotFoundError):
        await task_regenerate_clip({"job_id": "J1"}, "NOPE", new_prompt="x")

    final = upsert_calls[-1]
    assert final["status"] == "failed"
    assert final["progress_stage"] == "failed"
    assert "not found" in final["error"]


@pytest.mark.asyncio
async def test_task_marks_failed_on_generic_exception(monkeypatch):
    upsert_calls = []

    async def _record(job_id, **kwargs):
        upsert_calls.append(kwargs)

    async def _fake_regen(*args, **kwargs):
        raise RuntimeError("upstream timeout")

    monkeypatch.setattr("core.scheduler._upsert_job_status", _record)
    monkeypatch.setattr("layers.L3_visual.regenerate.regenerate_clip", _fake_regen)

    with pytest.raises(RuntimeError, match="upstream timeout"):
        await task_regenerate_clip({"job_id": "J1"}, "C1", new_prompt="x")

    final = upsert_calls[-1]
    assert final["status"] == "failed"
    assert "upstream timeout" in final["error"]


@pytest.mark.asyncio
async def test_task_works_without_job_id_in_ctx(monkeypatch):
    upsert_called = False

    async def _record(job_id, **kwargs):
        nonlocal upsert_called
        upsert_called = True

    fake_result = RegenerateResult(
        clip_id="C1",
        new_version=2,
        new_video_url="http://new.mp4",
        new_tail_frame_url=None,
        dirty_clip_ids=[],
        cost_cny=1.0,
        duration_ms=5000,
    )

    async def _fake_regen(*args, **kwargs):
        return fake_result

    monkeypatch.setattr("core.scheduler._upsert_job_status", _record)
    monkeypatch.setattr("layers.L3_visual.regenerate.regenerate_clip", _fake_regen)

    result = await task_regenerate_clip({}, "C1", new_prompt="x")

    assert result["status"] == "done"
    assert not upsert_called
