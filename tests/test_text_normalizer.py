from __future__ import annotations


def test_to_simplified_zh_fallback_converts_common_subtitle_text(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "opencc":
            raise ImportError("opencc missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    from layers.L5_postprod.text_normalizer import to_simplified_zh

    assert to_simplified_zh("這個視頻裡的畫面錯亂") == "这个视频里的画面错乱"
    assert to_simplified_zh("字幕還是繁體中文") == "字幕还是繁体中文"


def test_build_ass_content_normalizes_traditional_words():
    from layers.L4_audio.voiceover import WordTimestamp
    from layers.L5_postprod.captions import build_ass_content

    ass = build_ass_content(
        [
            WordTimestamp(word="這", start_ms=0, end_ms=80),
            WordTimestamp(word="個", start_ms=80, end_ms=160),
            WordTimestamp(word="視", start_ms=160, end_ms=240),
            WordTimestamp(word="頻", start_ms=240, end_ms=320),
        ]
    )

    assert "这个视频" in ass
    assert "這個視頻" not in ass


def test_retime_word_timestamps_scales_to_media_duration():
    from layers.L4_audio.voiceover import WordTimestamp
    from layers.L5_postprod.captions import _retime_word_timestamps

    words = [
        WordTimestamp(word="第", start_ms=0, end_ms=400),
        WordTimestamp(word="一", start_ms=400, end_ms=1000),
    ]

    scaled = _retime_word_timestamps(words, target_duration_ms=600)

    assert scaled[0].start_ms == 0
    assert scaled[0].end_ms == 240
    assert scaled[1].start_ms == 240
    assert scaled[1].end_ms == 600


def test_retime_word_timestamps_keeps_original_when_diff_is_small():
    from layers.L4_audio.voiceover import WordTimestamp
    from layers.L5_postprod.captions import _retime_word_timestamps

    words = [
        WordTimestamp(word="测", start_ms=0, end_ms=500),
        WordTimestamp(word="试", start_ms=500, end_ms=1000),
    ]

    same = _retime_word_timestamps(words, target_duration_ms=1070)

    assert same is words


def test_burn_captions_from_word_timestamps_retunes_to_video_duration(monkeypatch, tmp_path):
    from layers.L4_audio.voiceover import WordTimestamp
    from layers.L5_postprod import captions

    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake")
    output = tmp_path / "out.mp4"

    seen = {}

    monkeypatch.setattr(captions, "_probe_media_duration_ms", lambda _path: 600)

    def fake_build_ass_content(word_timestamps, chars_per_line=12):
        seen["times"] = [(w.start_ms, w.end_ms) for w in word_timestamps]
        return "[Script Info]\n"

    class _Proc:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        return _Proc()

    monkeypatch.setattr(captions, "build_ass_content", fake_build_ass_content)
    monkeypatch.setattr(captions.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    import os

    original_unlink = os.unlink

    def safe_unlink(path):
        try:
            original_unlink(path)
        except FileNotFoundError:
            pass

    monkeypatch.setattr(captions.os, "unlink", safe_unlink)

    import anyio

    anyio.run(
        captions.burn_captions_from_word_timestamps,
        video,
        output,
        [
            WordTimestamp(word="第", start_ms=0, end_ms=400),
            WordTimestamp(word="一", start_ms=400, end_ms=1000),
        ],
    )

    assert seen["times"] == [(0, 240), (240, 600)]


def test_group_words_to_lines_prefers_two_line_wrap_over_hard_event_split():
    from layers.L4_audio.voiceover import WordTimestamp
    from layers.L5_postprod.captions import _group_words_to_lines

    text = "还没出牌，谷歌已经把AI生态撑起了。"
    words = []
    cursor = 0
    for ch in text:
        words.append(WordTimestamp(word=ch, start_ms=cursor, end_ms=cursor + 120))
        cursor += 120

    lines = _group_words_to_lines(words, chars_per_line=12)

    assert len(lines) == 1
    assert "\\N" in lines[0][0]
    assert "还没出牌" in lines[0][0]
    assert "谷歌已经把AI" in lines[0][0]


def test_group_words_to_lines_breaks_on_sentence_end():
    from layers.L4_audio.voiceover import WordTimestamp
    from layers.L5_postprod.captions import _group_words_to_lines

    text = "谷歌这次来真的。苹果还没出牌。"
    words = []
    cursor = 0
    for ch in text:
        words.append(WordTimestamp(word=ch, start_ms=cursor, end_ms=cursor + 100))
        cursor += 100

    lines = _group_words_to_lines(words, chars_per_line=12)

    assert len(lines) == 2
    assert lines[0][0].endswith("真的。")
    assert lines[1][0].startswith("苹果")
