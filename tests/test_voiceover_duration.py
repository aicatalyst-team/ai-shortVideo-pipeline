from __future__ import annotations

from unittest.mock import MagicMock


def test_probe_audio_duration_ms_uses_ffprobe(monkeypatch, tmp_path):
    import layers.L4_audio.voiceover as voiceover

    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"fake")

    def fake_run(cmd, **kwargs):
        assert cmd[0] == "ffprobe"
        assert str(audio) in cmd
        return MagicMock(returncode=0, stdout="27.432\n")

    monkeypatch.setattr(voiceover.subprocess, "run", fake_run)

    assert voiceover._probe_audio_duration_ms(audio) == 27432


def test_probe_audio_duration_ms_returns_zero_on_failure(monkeypatch, tmp_path):
    import layers.L4_audio.voiceover as voiceover

    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"fake")

    def fake_run(cmd, **kwargs):
        return MagicMock(returncode=1, stdout="")

    monkeypatch.setattr(voiceover.subprocess, "run", fake_run)

    assert voiceover._probe_audio_duration_ms(audio) == 0
