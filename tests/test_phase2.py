"""Phase 2 集成测试：音频层 + 后期包装

测试覆盖：
- 2.1 TTS 配音模块
- 2.2 音效匹配模块
- 2.3 BGM 匹配模块
- 2.4 FFmpeg 多轨混音
- 2.5 动态字幕系统
- 2.6 封面生成
- 2.7 多比例适配
- 2.8 压缩预设
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_voiceover_voice_presets():
    """2.1 验证音色预设配置完整"""
    from layers.L4_audio.voiceover import VOICE_PRESETS, DEFAULT_VOICE

    assert len(VOICE_PRESETS) >= 5
    assert DEFAULT_VOICE in VOICE_PRESETS

    for key, preset in VOICE_PRESETS.items():
        assert "voice_type" in preset
        assert "name" in preset
        assert preset["voice_type"].startswith("zh_")


def test_voiceover_request_payload():
    """2.1 验证 TTS 请求 payload 构建"""
    from layers.L4_audio.voiceover import _build_request_payload

    payload = _build_request_payload(
        text="测试文本",
        voice_type="zh_female_wenrouxiaoya_uranus_bigtts",
        appid="test_appid",
    )

    assert payload["app"]["appid"] == "test_appid"
    assert payload["audio"]["voice_type"] == "zh_female_wenrouxiaoya_uranus_bigtts"
    assert payload["request"]["text"] == "测试文本"
    assert payload["audio"]["speed_ratio"] == 1.0


def test_sfx_categories():
    """2.2 验证音效分类库完整性"""
    from layers.L4_audio.sfx import SFX_CATEGORIES

    assert len(SFX_CATEGORIES) >= 20
    required = ["cat_meow", "explosion", "rain", "comedy", "office"]
    for cat in required:
        assert cat in SFX_CATEGORIES
        assert "name" in SFX_CATEGORIES[cat]
        assert "tags" in SFX_CATEGORIES[cat]
        assert len(SFX_CATEGORIES[cat]["tags"]) >= 3


def test_sfx_list_categories():
    """2.2 验证分类列表接口"""
    from layers.L4_audio.sfx import list_categories

    cats = list_categories()
    assert len(cats) >= 20
    assert all("key" in c and "name" in c for c in cats)


def test_bgm_mood_info():
    """2.3 验证 BGM 情绪标签体系"""
    from layers.L4_audio.bgm import MOOD_INFO

    assert len(MOOD_INFO) >= 10
    required = ["epic", "funny", "healing", "suspense", "cyberpunk"]
    for mood in required:
        assert mood in MOOD_INFO
        assert "name" in MOOD_INFO[mood]
        assert "keywords" in MOOD_INFO[mood]


def test_bgm_keyword_match():
    """2.3 验证关键词匹配"""
    from layers.L4_audio.bgm import match_by_keywords

    result = match_by_keywords("这是一个搞笑的猫咪视频，非常欢乐有趣")
    assert result.mood == "funny"
    assert result.confidence > 0

    result2 = match_by_keywords("赛博朋克城市，未来科技感")
    assert result2.mood == "cyberpunk"


def test_bgm_keyword_match_fallback():
    """2.3 无匹配时回退到 chill"""
    from layers.L4_audio.bgm import match_by_keywords

    result = match_by_keywords("xyzabc123")
    assert result.mood == "chill"
    assert result.confidence == 0.3


def test_mixer_config():
    """2.4 验证混音配置数据结构"""
    from layers.L4_audio.mixer import MixConfig, AudioTrack

    track = AudioTrack(file_path=Path("test.mp3"), volume=0.8, delay_ms=1000)
    config = MixConfig(
        video_path=Path("video.mp4"),
        output_path=Path("out.mp4"),
        voiceover=track,
        bgm=AudioTrack(file_path=Path("bgm.mp3"), volume=0.3, loop=True),
    )
    assert config.voiceover.volume == 0.8
    assert config.bgm.loop is True
    assert len(config.sfx_tracks) == 0


def test_captions_from_list():
    """2.5 验证字幕列表转 CaptionItem"""
    from layers.L5_postprod.captions import from_captions_list

    items = from_captions_list(["第一句", "第二句", "第三句"], total_duration_sec=9.0)
    assert len(items) == 3
    assert items[0].start_sec == 0.0
    assert items[0].end_sec == 3.0
    assert items[1].start_sec == 3.0
    assert items[2].end_sec == 9.0


def test_captions_build_filters():
    """2.5 验证多风格滤镜构建"""
    from layers.L5_postprod.captions import (
        build_drawtext_filters, CaptionConfig, CaptionItem, _STYLE_PARAMS,
    )

    items = [CaptionItem(text="测试字幕", start_sec=0, end_sec=3)]

    for style in _STYLE_PARAMS:
        config = CaptionConfig(items=items, style=style)
        vf = build_drawtext_filters(config)
        assert "drawtext" in vf
        assert "测试字幕" in vf


def test_captions_escape():
    """2.5 验证特殊字符转义"""
    from layers.L5_postprod.captions import _escape_text

    assert "\\:" in _escape_text("时间:12:00")
    assert "\\'" in _escape_text("it's")
    assert "%%" in _escape_text("100%")


def test_captions_trim_long_lines():
    """2.5 字幕过长时必须裁短，避免横向超屏。"""
    from layers.L5_postprod.captions import (
        CaptionConfig,
        CaptionItem,
        _trim_caption_text,
        build_drawtext_filters,
    )

    text = "这是一条非常非常长的字幕如果不裁短就会超出屏幕"
    assert len(_trim_caption_text(text)) <= 16
    vf = build_drawtext_filters(CaptionConfig(items=[CaptionItem(text=text, start_sec=0, end_sec=3)]))
    assert "这是一条非常非常长的字幕如果不" in vf
    assert "就会超出屏幕" not in vf


def test_cover_config():
    """2.6 验证封面配置"""
    from layers.L5_postprod.cover import CoverConfig, _build_cover_filter

    config = CoverConfig(title="测试标题", subtitle="副标题")
    vf = _build_cover_filter(config)
    assert "drawtext" in vf
    assert "测试标题" in vf
    assert "副标题" in vf


def test_cover_layouts():
    """2.6 验证不同布局"""
    from layers.L5_postprod.cover import CoverConfig, _build_cover_filter

    for layout in ("top", "center", "bottom", "top_left"):
        config = CoverConfig(title="标题", layout=layout)
        vf = _build_cover_filter(config)
        assert "drawtext" in vf


def test_multi_ratio_config():
    """2.7 验证比例配置"""
    from layers.L5_postprod.multi_ratio import _RATIO_CONFIG, _detect_ratio

    assert "9:16" in _RATIO_CONFIG
    assert "1:1" in _RATIO_CONFIG
    assert "16:9" in _RATIO_CONFIG

    assert _detect_ratio(1080, 1920) == "9:16"
    assert _detect_ratio(1920, 1080) == "16:9"
    assert _detect_ratio(1080, 1080) == "1:1"


def test_multi_ratio_vf_build():
    """2.7 验证滤镜生成"""
    from layers.L5_postprod.multi_ratio import _build_vf

    vf = _build_vf("9:16", "1:1")
    assert "crop" in vf
    assert "1080" in vf

    vf2 = _build_vf("9:16", "16:9")
    assert "split" in vf2 or "scale" in vf2

    vf_same = _build_vf("9:16", "9:16")
    assert vf_same == ""


def test_compress_presets():
    """2.8 验证压缩预设"""
    from layers.L5_postprod.editor import _COMPRESS_PRESETS, list_presets

    assert "preview" in _COMPRESS_PRESETS
    assert "douyin" in _COMPRESS_PRESETS
    assert "bilibili" in _COMPRESS_PRESETS
    assert "hd" in _COMPRESS_PRESETS

    assert _COMPRESS_PRESETS["preview"]["crf"] > _COMPRESS_PRESETS["hd"]["crf"]

    presets = list_presets()
    assert len(presets) == 4


def test_webhook_imports():
    """2.9 验证 webhook 模块能正确导入音频和后期模块"""
    try:
        from api.webhooks import (
            tts_synthesize, analyze_scene_sfx, analyze_mood,
            mix_simple, burn_captions, generate_cover,
            generate_all_ratios, compress,
        )
    except ImportError as e:
        raise AssertionError(f"Webhook import failed: {e}")


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            print(f"  PASS  {test_fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {test_fn.__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Phase 2 tests: {passed} passed, {failed} failed, {passed + failed} total")
    if failed:
        sys.exit(1)
