"""Phase 3.5 集成测试：角色一致性系统"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── characters.yaml 加载 ──

class TestCharacterConfig:
    def test_characters_yaml_exists(self):
        cfg_path = Path(__file__).resolve().parent.parent / "config" / "characters.yaml"
        assert cfg_path.is_file(), f"characters.yaml 不存在: {cfg_path}"

    def test_characters_yaml_valid(self):
        import yaml
        cfg_path = Path(__file__).resolve().parent.parent / "config" / "characters.yaml"
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        assert "default_character" in data
        character_keys = [k for k in data if k != "default_character"]
        assert len(character_keys) >= 2, "至少需要 2 个角色定义"

    def test_each_character_has_required_fields(self):
        import yaml
        cfg_path = Path(__file__).resolve().parent.parent / "config" / "characters.yaml"
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        for key, val in data.items():
            if key == "default_character":
                continue
            assert "display_name" in val, f"{key} 缺少 display_name"
            assert "description" in val, f"{key} 缺少 description"
            assert "visual_tags" in val, f"{key} 缺少 visual_tags"
            assert "ref_images" in val, f"{key} 缺少 ref_images"
            assert "compatible_styles" in val, f"{key} 缺少 compatible_styles"
            assert isinstance(val["compatible_styles"], list)

    def test_character_refs_dir_exists(self):
        refs_dir = Path(__file__).resolve().parent.parent / "config" / "character_refs"
        assert refs_dir.is_dir(), f"character_refs 目录不存在: {refs_dir}"


# ── CharacterManager ──

class TestCharacterManager:
    def test_load_characters(self):
        from layers.L2_creative.character_manager import _load_characters
        chars = _load_characters(force=True)
        assert len(chars) >= 2

    def test_get_character_by_key(self):
        from layers.L2_creative.character_manager import get_character, _load_characters
        _load_characters(force=True)
        char = get_character("su_wan")
        assert char is not None
        assert char.display_name == "苏晚"
        assert char.visual_tags

    def test_get_character_by_display_name(self):
        from layers.L2_creative.character_manager import get_character, _load_characters
        _load_characters(force=True)
        char = get_character("苏晚")
        assert char is not None
        assert char.key == "su_wan"

    def test_get_character_nonexistent(self):
        from layers.L2_creative.character_manager import get_character, _load_characters
        _load_characters(force=True)
        char = get_character("不存在的角色")
        assert char is None

    def test_get_default_character(self):
        from layers.L2_creative.character_manager import get_default_character, _load_characters
        _load_characters(force=True)
        char = get_default_character()
        assert char is not None
        assert char.key == "su_wan"

    def test_list_characters(self):
        from layers.L2_creative.character_manager import list_characters, _load_characters
        _load_characters(force=True)
        chars = list_characters()
        assert len(chars) >= 4
        names = [c.display_name for c in chars]
        assert "苏晚" in names
        assert "林悦" in names
        assert "陈星" in names
        assert "叶澄" in names

    def test_get_characters_for_style(self):
        from layers.L2_creative.character_manager import get_characters_for_style, _load_characters
        _load_characters(force=True)
        chars = get_characters_for_style("cyberpunk_military")
        assert len(chars) >= 1
        keys = [c.key for c in chars]
        assert "su_wan" in keys

    def test_resolve_operator_to_character(self):
        from layers.L2_creative.character_manager import resolve_operator_to_character, _load_characters
        _load_characters(force=True)
        char = resolve_operator_to_character("苏晚", "cyberpunk_military")
        assert char is not None
        assert char.key == "su_wan"

    def test_resolve_unknown_operator_falls_back(self):
        from layers.L2_creative.character_manager import resolve_operator_to_character, _load_characters
        _load_characters(force=True)
        char = resolve_operator_to_character("未知角色", "cute_healing")
        assert char is not None

    def test_character_visual_tags_not_empty(self):
        from layers.L2_creative.character_manager import list_characters, _load_characters
        _load_characters(force=True)
        for c in list_characters():
            assert len(c.visual_tags) > 20, f"{c.key} visual_tags 过短"

    def test_character_ref_paths_defined(self):
        from layers.L2_creative.character_manager import list_characters, _load_characters
        _load_characters(force=True)
        for c in list_characters():
            assert "front" in c.ref_images, f"{c.key} 缺少 front ref_image"
            assert "side" in c.ref_images, f"{c.key} 缺少 side ref_image"


# ── 风格模板角色更新 ──

class TestStyleTemplateOperators:
    def test_templates_use_new_characters(self):
        from layers.L2_creative.style_engine import load_all_templates
        templates = load_all_templates(force=True)
        assert len(templates) >= 4
        old_names = {"红狼", "威龙", "露娜", "骧爪", "牧羊人", "蜂医", "乌鲁鲁", "银翼"}
        for name, tpl in templates.items():
            for op in tpl.operators:
                assert op not in old_names, f"模板 {name} 仍引用旧角色 {op}"

    def test_all_templates_have_operators(self):
        from layers.L2_creative.style_engine import load_all_templates
        templates = load_all_templates(force=True)
        for name, tpl in templates.items():
            assert len(tpl.operators) >= 2, f"模板 {name} 角色少于 2 个"


# ── 管线参数传递（不调 API，只验证函数签名）──

class TestPipelineSignatures:
    def test_generate_image_accepts_character_ref(self):
        import inspect
        from layers.L3_visual.text_to_image import generate_image
        sig = inspect.signature(generate_image)
        assert "character_ref_path" in sig.parameters

    def test_image_to_video_accepts_character_ref(self):
        import inspect
        from layers.L3_visual.providers.kling_v3 import image_to_video
        sig = inspect.signature(image_to_video)
        assert "character_ref_path" in sig.parameters

    def test_generate_clip_accepts_character_ref(self):
        import inspect
        from layers.L3_visual.image_to_video import generate_clip
        sig = inspect.signature(generate_clip)
        assert "character_ref_path" in sig.parameters
        assert "first_frame_path" in sig.parameters
        assert "camera_control" in sig.parameters

    def test_generate_clip_sequence_accepts_character_ref(self):
        import inspect
        from layers.L3_visual.image_to_video import generate_clip_sequence
        sig = inspect.signature(generate_clip_sequence)
        assert "character_ref_path" in sig.parameters
        assert "chain_frames" in sig.parameters

    def test_lobster_visual_accepts_character(self):
        import inspect
        from layers.L2_creative.chains import lobster_visual
        sig = inspect.signature(lobster_visual)
        assert "character" in sig.parameters

    def test_generate_clip_sequence_chains_tail_frames(self, tmp_path, monkeypatch):
        from layers.L2_creative.style_engine import StyleTemplate
        import layers.L3_visual.image_to_video as pipeline

        calls = []

        async def fake_generate_clip(**kwargs):
            calls.append(kwargs)
            Path(kwargs["output_path"]).write_bytes(b"video")
            return None

        def fake_extract_last_frame(video_path, output_path):
            Path(output_path).write_bytes(b"tail")
            return output_path

        monkeypatch.setattr(pipeline, "generate_clip", fake_generate_clip)
        monkeypatch.setattr(pipeline, "extract_last_frame", fake_extract_last_frame)

        style = StyleTemplate(
            name="test",
            display_name="test",
            core_concept="",
            visual_style="",
            caption_style="minimal",
            hook_rule="",
            video_spec="",
        )
        clips = [
            {"clip_no": 1, "duration_sec": 5, "scene_summary": "s1"},
            {"clip_no": 2, "duration_sec": 5, "scene_summary": "s2"},
            {"clip_no": 3, "duration_sec": 5, "scene_summary": "s3"},
        ]

        import asyncio
        asyncio.run(pipeline.generate_clip_sequence(clips, str(tmp_path), style, chain_frames=True))

        assert calls[0]["first_frame_path"] is None
        assert calls[1]["first_frame_path"].endswith("tail_01.png")
        assert calls[2]["first_frame_path"].endswith("tail_02.png")


# ── 音色预设更新 ──

class TestVoicePresets:
    def test_voice_presets_use_new_characters(self):
        from layers.L4_audio.voiceover import VOICE_PRESETS
        old_names = {"红狼", "威龙", "露娜"}
        for key, preset in VOICE_PRESETS.items():
            assert preset["name"] not in old_names, f"音色 {key} 仍引用旧角色 {preset['name']}"

    def test_default_voice_exists(self):
        from layers.L4_audio.voiceover import VOICE_PRESETS, DEFAULT_VOICE
        assert DEFAULT_VOICE in VOICE_PRESETS


# ── Settings 配置 ──

class TestSettings:
    def test_characters_config_path_in_settings(self):
        from config.settings import Settings
        s = Settings()
        assert hasattr(s, "characters_config_path")
        assert "characters.yaml" in str(s.characters_config_path)
