from __future__ import annotations

import subprocess
import asyncio
from types import SimpleNamespace

from api.webhooks import _rebuild_timed_captions_from_narration
from layers.L3_visual.image_to_video import extract_last_frame
from layers.L3_visual.providers import kling_v3


def test_rebuild_captions_uses_plan_when_clips_have_narration():
    clips = [
        {"narration_segment": "第一段旁白", "duration_sec": 5},
        {"narration_segment": "第二段旁白", "duration_sec": 5},
    ]

    items = _rebuild_timed_captions_from_narration(clips, "全局旁白不应优先", 10)

    assert items
    assert items[0].text == "第一段旁白"
    assert items[-1].end_sec == 10


def test_rebuild_captions_falls_back_to_text_when_plan_empty():
    items = _rebuild_timed_captions_from_narration([], "这是全局旁白文本，需要用于字幕", 6)

    assert items
    assert items[0].start_sec == 0
    assert items[-1].end_sec == 6


def test_rebuild_captions_returns_empty_when_no_data():
    assert _rebuild_timed_captions_from_narration([], "", 0) == []


def test_extract_last_frame_strategy2_uses_ffprobe_duration(monkeypatch, tmp_path):
    video_path = tmp_path / "clip.mp4"
    output_path = tmp_path / "tail.png"
    video_path.write_bytes(b"video")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "ffmpeg" and "-sseof" in cmd and "-1.0" in cmd:
            output_path.write_bytes(b"")
            return subprocess.CompletedProcess(cmd, 0)
        if cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(cmd, 0, stdout="5.040\n", stderr="")
        if cmd[0] == "ffmpeg" and "-ss" in cmd:
            output_path.write_bytes(b"png")
            return subprocess.CompletedProcess(cmd, 0)
        raise AssertionError(cmd)

    monkeypatch.setattr("layers.L3_visual.image_to_video.subprocess.run", fake_run)

    assert extract_last_frame(str(video_path), str(output_path)) == str(output_path)
    assert len(calls) == 3
    assert calls[0][0] == "ffmpeg"
    assert "-sseof" in calls[0]
    assert "-1.0" in calls[0]
    assert calls[1][0] == "ffprobe"
    assert calls[2][0] == "ffmpeg"
    assert "-ss" in calls[2]
    assert "4.540" in calls[2]


def test_extract_last_frame_fallback_when_ffprobe_fails_uses_strategy3(monkeypatch, tmp_path):
    video_path = tmp_path / "clip.mp4"
    output_path = tmp_path / "tail.png"
    video_path.write_bytes(b"video")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "ffmpeg" and "-sseof" in cmd and "-1.0" in cmd:
            output_path.write_bytes(b"")
            return subprocess.CompletedProcess(cmd, 0)
        if cmd[0] == "ffprobe":
            raise subprocess.CalledProcessError(1, cmd)
        if cmd[0] == "ffmpeg" and "-sseof" in cmd and "-0.04" in cmd:
            output_path.write_bytes(b"png")
            return subprocess.CompletedProcess(cmd, 0)
        raise AssertionError(cmd)

    monkeypatch.setattr("layers.L3_visual.image_to_video.subprocess.run", fake_run)

    assert extract_last_frame(str(video_path), str(output_path)) == str(output_path)
    assert len(calls) == 3
    assert "-sseof" in calls[0]
    assert "-1.0" in calls[0]
    assert calls[1][0] == "ffprobe"
    assert "-sseof" in calls[2]
    assert "-0.04" in calls[2]


def test_extract_last_frame_strategy1_sseof_update_succeeds(monkeypatch, tmp_path):
    """策略 1 首次就成功，不调用后续策略。"""
    video_path = tmp_path / "clip.mp4"
    output_path = tmp_path / "tail.png"
    video_path.write_bytes(b"video")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        output_path.write_bytes(b"png")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("layers.L3_visual.image_to_video.subprocess.run", fake_run)

    assert extract_last_frame(str(video_path), str(output_path)) == str(output_path)
    assert len(calls) == 1
    assert calls[0][0] == "ffmpeg"
    assert "-sseof" in calls[0]
    assert "-1.0" in calls[0]
    assert "-update" in calls[0]


def test_extract_last_frame_falls_through_to_strategy2_ffprobe(monkeypatch, tmp_path):
    """策略 1 输出 0 字节，降级 ffprobe 策略 2 成功。"""
    video_path = tmp_path / "clip.mp4"
    output_path = tmp_path / "tail.png"
    video_path.write_bytes(b"video")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if len(calls) == 1:
            output_path.write_bytes(b"")
            return subprocess.CompletedProcess(cmd, 0)
        if cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(cmd, 0, stdout="5.04\n", stderr="")
        if cmd[0] == "ffmpeg" and "-ss" in cmd:
            output_path.write_bytes(b"png")
            return subprocess.CompletedProcess(cmd, 0)
        raise AssertionError(cmd)

    monkeypatch.setattr("layers.L3_visual.image_to_video.subprocess.run", fake_run)

    assert extract_last_frame(str(video_path), str(output_path)) == str(output_path)
    assert len(calls) == 3
    assert "-sseof" in calls[0]
    assert calls[1][0] == "ffprobe"
    assert "-ss" in calls[2]


def test_extract_last_frame_all_three_strategies_fail_raises(monkeypatch, tmp_path):
    """3 策略全失败时正确抛 RuntimeError（行为兼容旧版）。"""
    video_path = tmp_path / "clip.mp4"
    output_path = tmp_path / "tail.png"
    video_path.write_bytes(b"video")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "ffmpeg":
            output_path.write_bytes(b"")
            return subprocess.CompletedProcess(cmd, 0)
        if cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(cmd, 0, stdout="5.04\n", stderr="")
        raise AssertionError(cmd)

    monkeypatch.setattr("layers.L3_visual.image_to_video.subprocess.run", fake_run)

    try:
        extract_last_frame(str(video_path), str(output_path))
    except RuntimeError as exc:
        assert f"抽末帧失败或文件为空: {output_path}" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
    assert len(calls) == 4


def test_models_without_camera_control_skipped(monkeypatch, tmp_path):
    image_path = tmp_path / "first.png"
    output_path = tmp_path / "clip.mp4"
    image_path.write_bytes(b"image")
    posted_payloads: list[dict] = []

    class FakeResponse:
        def __init__(self, data=None, content=b""):
            self._data = data or {}
            self.content = content

        def json(self):
            return self._data

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            posted_payloads.append(json or {})
            return FakeResponse({"code": 0, "data": {"task_id": "task-1"}})

        async def get(self, url, headers=None):
            if url.endswith("/task-1"):
                return FakeResponse(
                    {
                        "data": {
                            "task_status": "succeed",
                            "task_result": {"videos": [{"url": "https://example.test/video.mp4"}]},
                        }
                    }
                )
            return FakeResponse(content=b"video-bytes")

    async def fake_sleep(delay):
        return None

    monkeypatch.setattr(
        kling_v3,
        "get_settings",
        lambda: SimpleNamespace(
            kling_video_model="kling-v2-5-turbo",
            kling_base_url="https://kling.example.test",
        ),
    )
    monkeypatch.setattr(kling_v3, "kling_headers", lambda: {})
    monkeypatch.setattr(kling_v3.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(kling_v3.asyncio, "sleep", fake_sleep)

    result = asyncio.run(
        kling_v3.image_to_video(
            image_path=str(image_path),
            prompt="test prompt",
            output_path=str(output_path),
            camera_control={"type": "push_in", "config": {"zoom": 5}},
        )
    )

    assert result.local_path == str(output_path)
    assert posted_payloads
    assert "camera_control" not in posted_payloads[0]
