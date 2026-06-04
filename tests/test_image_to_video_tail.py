from __future__ import annotations

from unittest.mock import MagicMock


def test_extract_last_frame_uses_ffprobe_duration_then_seek(monkeypatch, tmp_path):
    from layers.L3_visual.image_to_video import extract_last_frame
    import layers.L3_visual.image_to_video as module

    calls = []
    output_path = tmp_path / "tail.png"

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "ffprobe":
            return MagicMock(stdout="5.000\n", stderr="")
        output_path.write_bytes(b"png")
        return MagicMock(stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    result = extract_last_frame("clip.mp4", str(output_path))

    assert result == str(output_path)
    assert calls[0][0] == "ffprobe"
    assert calls[1][0] == "ffmpeg"
    assert "-ss" in calls[1]
    assert calls[1][calls[1].index("-ss") + 1] == "4.920"
    assert "-sseof" not in calls[1]


def test_extract_last_frame_rejects_invalid_duration(monkeypatch, tmp_path):
    from layers.L3_visual.image_to_video import extract_last_frame
    import layers.L3_visual.image_to_video as module

    def _fake_run(cmd, **kwargs):
        return MagicMock(stdout="not-a-number\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    try:
        extract_last_frame("clip.mp4", str(tmp_path / "tail.png"))
    except RuntimeError as exc:
        assert "无法读取视频时长" in str(exc)
    else:
        raise AssertionError("extract_last_frame should reject invalid ffprobe duration")
