from __future__ import annotations

import subprocess

import pytest

from layers.L5_postprod import av_sync
from layers.L5_postprod.av_sync import (
    AVDriftTooLargeError,
    AvSyncReport,
    build_av_sync_report,
    check_and_correct_av_sync,
    probe_media_duration,
)


def _touch(path, data: bytes = b"x"):
    path.write_bytes(data)
    return path


def test_probe_media_duration_success(monkeypatch, tmp_path):
    media = _touch(tmp_path / "media.mp4")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="5.04\n", stderr="")

    monkeypatch.setattr(av_sync.subprocess, "run", fake_run)

    assert probe_media_duration(media) == 5.04


def test_probe_media_duration_returns_zero_when_file_missing(tmp_path):
    assert probe_media_duration(tmp_path / "missing.mp4") == 0.0


def test_probe_media_duration_returns_zero_when_ffprobe_fails(monkeypatch, tmp_path):
    media = _touch(tmp_path / "media.mp4")

    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(av_sync.subprocess, "run", fake_run)

    assert probe_media_duration(media) == 0.0


def test_build_report_pass_when_drift_under_05s(monkeypatch, tmp_path):
    final = _touch(tmp_path / "mixed.mp4")
    monkeypatch.setattr(av_sync, "probe_video_duration", lambda path: 10.0)
    monkeypatch.setattr(av_sync, "probe_audio_duration", lambda path: 10.3)
    monkeypatch.setattr(av_sync, "probe_media_duration", lambda path: 10.3)

    report = build_av_sync_report(tmp_path / "video.mp4", tmp_path / "voice.mp3", final)

    assert report.severity == "pass"
    assert report.drift_sec == pytest.approx(0.3)


def test_build_report_soft_fix_when_drift_between_05_and_12s(monkeypatch, tmp_path):
    final = _touch(tmp_path / "mixed.mp4")
    monkeypatch.setattr(av_sync, "probe_video_duration", lambda path: 10.0)
    monkeypatch.setattr(av_sync, "probe_audio_duration", lambda path: 11.0)
    monkeypatch.setattr(av_sync, "probe_media_duration", lambda path: 11.0)

    report = build_av_sync_report(tmp_path / "video.mp4", tmp_path / "voice.mp3", final)

    assert report.severity == "soft_fix"
    assert report.drift_sec == pytest.approx(1.0)


def test_build_report_hard_fail_when_drift_above_12s(monkeypatch, tmp_path):
    final = _touch(tmp_path / "mixed.mp4")
    monkeypatch.setattr(av_sync, "probe_video_duration", lambda path: 10.0)
    monkeypatch.setattr(av_sync, "probe_audio_duration", lambda path: 12.0)
    monkeypatch.setattr(av_sync, "probe_media_duration", lambda path: 12.0)

    report = build_av_sync_report(tmp_path / "video.mp4", tmp_path / "voice.mp3", final)

    assert report.severity == "hard_fail"
    assert report.drift_sec == pytest.approx(2.0)


def test_build_report_no_voiceover_passes(monkeypatch, tmp_path):
    final = _touch(tmp_path / "mixed.mp4")
    monkeypatch.setattr(av_sync, "probe_video_duration", lambda path: 10.0)
    monkeypatch.setattr(av_sync, "probe_media_duration", lambda path: 10.0)

    report = build_av_sync_report(tmp_path / "video.mp4", None, final)

    assert report.severity == "pass"
    assert report.drift_sec == 0.0
    assert report.correction_applied == "no_voiceover"


def test_check_and_correct_returns_pass_unchanged(monkeypatch, tmp_path):
    video = _touch(tmp_path / "video.mp4")
    voice = _touch(tmp_path / "voice.mp3")
    mixed = _touch(tmp_path / "mixed.mp4")
    corrected = tmp_path / "mixed_corrected.mp4"
    monkeypatch.setattr(av_sync, "probe_video_duration", lambda path: 10.0)
    monkeypatch.setattr(av_sync, "probe_audio_duration", lambda path: 10.2)
    monkeypatch.setattr(av_sync, "probe_media_duration", lambda path: 10.2)
    monkeypatch.setattr(
        av_sync,
        "apply_av_sync_correction",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not correct")),
    )

    report = check_and_correct_av_sync(video, voice, mixed, corrected)

    assert report.severity == "pass"
    assert not corrected.exists()


def test_check_and_correct_hard_fail_raises(monkeypatch, tmp_path):
    video = _touch(tmp_path / "video.mp4")
    voice = _touch(tmp_path / "voice.mp3")
    mixed = _touch(tmp_path / "mixed.mp4")
    corrected = tmp_path / "mixed_corrected.mp4"
    monkeypatch.setattr(av_sync, "probe_video_duration", lambda path: 10.0)
    monkeypatch.setattr(av_sync, "probe_audio_duration", lambda path: 12.0)
    monkeypatch.setattr(av_sync, "probe_media_duration", lambda path: 12.0)

    with pytest.raises(AVDriftTooLargeError) as exc:
        check_and_correct_av_sync(video, voice, mixed, corrected)

    assert exc.value.report.severity == "hard_fail"
    assert exc.value.report.drift_sec == pytest.approx(2.0)


def test_check_and_correct_soft_fix_trims_video_when_video_longer(monkeypatch, tmp_path):
    video = _touch(tmp_path / "video.mp4")
    voice = _touch(tmp_path / "voice.mp3")
    mixed = _touch(tmp_path / "mixed.mp4")
    corrected = tmp_path / "mixed_corrected.mp4"
    calls: list[list[str]] = []
    monkeypatch.setattr(av_sync, "probe_video_duration", lambda path: 10.0)
    monkeypatch.setattr(av_sync, "probe_audio_duration", lambda path: 9.0)
    monkeypatch.setattr(av_sync, "probe_media_duration", lambda path: 9.0)

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        corrected.write_bytes(b"fixed")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(av_sync.subprocess, "run", fake_run)

    report = check_and_correct_av_sync(video, voice, mixed, corrected)

    assert report.severity == "soft_fix"
    assert report.correction_applied == "trim_video_to_9.00s"
    assert calls
    assert "-t" in calls[0]
    assert "9.000" in calls[0]


def test_to_feishu_line_includes_severity_icon():
    assert "✅" in AvSyncReport(
        video_sec=10, voiceover_sec=10, final_sec=10, drift_sec=0, severity="pass"
    ).to_feishu_line()
    assert "⚠️" in AvSyncReport(
        video_sec=10, voiceover_sec=11, final_sec=11, drift_sec=1, severity="soft_fix"
    ).to_feishu_line()
    assert "🔴" in AvSyncReport(
        video_sec=10, voiceover_sec=12, final_sec=12, drift_sec=2, severity="hard_fail"
    ).to_feishu_line()
