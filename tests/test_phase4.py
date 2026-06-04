"""Phase 4 集成测试：内容赛道对齐（风格重塑 + 创意链重写）"""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "config" / "style_templates"

REQUIRED_TEMPLATES = [
    "hot_news_commentary",
    "knowledge_explainer",
    "emotional_story",
    "curiosity_facts",
    "social_insight",
]

REQUIRED_YAML_FIELDS = [
    "name",
    "display_name",
    "core_concept",
    "visual_style",
    "caption_style",
    "hook_rule",
    "video_spec",
    "image_prompt_suffix",
    "kling_negative_prompt",
    "aspect_ratio",
    "duration_range",
    "tags_prefix",
]


# ── 新模板 YAML 完整性 ──

class TestNewTemplateYAML:
    def test_all_5_templates_exist(self):
        for name in REQUIRED_TEMPLATES:
            path = TEMPLATES_DIR / f"{name}.yaml"
            assert path.is_file(), f"模板文件不存��: {path}"

    @pytest.mark.parametrize("template_name", REQUIRED_TEMPLATES)
    def test_template_has_required_fields(self, template_name):
        path = TEMPLATES_DIR / f"{template_name}.yaml"
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        for field in REQUIRED_YAML_FIELDS:
            assert field in data, f"{template_name} 缺少字段: {field}"

    @pytest.mark.parametrize("template_name", REQUIRED_TEMPLATES)
    def test_template_name_matches_filename(self, template_name):
        path = TEMPLATES_DIR / f"{template_name}.yaml"
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["name"] == template_name

    @pytest.mark.parametrize("template_name", REQUIRED_TEMPLATES)
    def test_template_has_hook_rule(self, template_name):
        path = TEMPLATES_DIR / f"{template_name}.yaml"
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "前3秒" in data["hook_rule"], f"{template_name} hook_rule 应包含前3秒策略"

    @pytest.mark.parametrize("template_name", REQUIRED_TEMPLATES)
    def test_template_aspect_ratio_vertical(self, template_name):
        path = TEMPLATES_DIR / f"{template_name}.yaml"
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["aspect_ratio"] == "9:16", f"{template_name} 应为竖屏 9:16"

    @pytest.mark.parametrize("template_name", REQUIRED_TEMPLATES)
    def test_template_operators_is_empty(self, template_name):
        path = TEMPLATES_DIR / f"{template_name}.yaml"
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data.get("operators", []) == [], f"{template_name} 新模板不应有 operators"


# ── StyleEngine 加载 ──

class TestStyleEnginePhase4:
    def test_load_all_new_templates(self):
        from layers.L2_creative.style_engine import load_all_templates
        templates = load_all_templates(force=True)
        for name in REQUIRED_TEMPLATES:
            assert name in templates, f"StyleEngine 未加载模板: {name}"

    def test_get_template_by_name(self):
        from layers.L2_creative.style_engine import get_template
        for name in REQUIRED_TEMPLATES:
            tpl = get_template(name)
            assert tpl.name == name
            assert tpl.display_name

    def test_system_prompt_contains_style_info(self):
        from layers.L2_creative.style_engine import get_template
        tpl = get_template("hot_news_commentary")
        prompt = tpl.system_prompt()
        assert "热搜解说" in prompt
        assert "风格档案" in prompt

    def test_enrich_image_prompt(self):
        from layers.L2_creative.style_engine import get_template
        tpl = get_template("curiosity_facts")
        enriched = tpl.enrich_image_prompt("deep sea creature")
        assert "dark mysterious" in enriched


# ── chains.py 创意链重写 ──

class TestChainsPhase4:
    def test_lobster_creative_exists(self):
        from layers.L2_creative.chains import lobster_creative
        import inspect
        assert inspect.iscoroutinefunction(lobster_creative)

    def test_lobster_review_exists(self):
        from layers.L2_creative.chains import lobster_review
        assert callable(lobster_review)

    def test_lobster_evaluate_exists(self):
        from layers.L2_creative.chains import lobster_evaluate
        import inspect
        assert inspect.iscoroutinefunction(lobster_evaluate)

    def test_lobster_visual_exists(self):
        from layers.L2_creative.chains import lobster_visual
        import inspect
        assert inspect.iscoroutinefunction(lobster_visual)

    def test_lobster_rewrite_exists(self):
        from layers.L2_creative.chains import lobster_rewrite
        import inspect
        assert inspect.iscoroutinefunction(lobster_rewrite)

    def test_lobster_vertical_exists(self):
        from layers.L2_creative.chains import lobster_vertical
        import inspect
        assert inspect.iscoroutinefunction(lobster_vertical)

    def test_vertical_prompts_cover_all_templates(self):
        from layers.L2_creative.chains import VERTICAL_PROMPTS
        for name in REQUIRED_TEMPLATES:
            assert name in VERTICAL_PROMPTS, f"VERTICAL_PROMPTS 缺少: {name}"

    def test_style_voice_map_cover_all_templates(self):
        from layers.L2_creative.chains import STYLE_VOICE_MAP
        for name in REQUIRED_TEMPLATES:
            assert name in STYLE_VOICE_MAP, f"STYLE_VOICE_MAP 缺少: {name}"

    def test_get_voice_for_style(self):
        from layers.L2_creative.chains import get_voice_for_style
        assert get_voice_for_style("hot_news_commentary") == "narrator_male"
        assert get_voice_for_style("emotional_story") == "su_wan"
        assert get_voice_for_style("knowledge_explainer") == "narrator_female_calm"

    def test_format_evaluation_output(self):
        from layers.L2_creative.chains import format_evaluation
        evaluation = {
            "plans": [{
                "script_index": 1,
                "angle": "测试角度",
                "total_duration_sec": 25,
                "clips": [
                    {"clip_no": 1, "duration_sec": 5, "scene_summary": "测试场景", "narration_segment": "测试旁白", "reason": "测试"},
                ],
                "quality": "standard",
                "quality_reason": "图文混剪",
            }]
        }
        msg, cost = format_evaluation(evaluation)
        assert "解说视频制作方案" in msg
        assert "测试角度" in msg
        assert cost > 0


# ── webhooks.py 指令体系 ──

class TestWebhooksPhase4:
    def test_default_style_is_hot_news(self):
        from api.webhooks import _current_style
        assert _current_style == "hot_news_commentary"

    def test_vertical_cmd_map_exists(self):
        from api.webhooks import _VERTICAL_CMD_MAP
        assert "解说" in _VERTICAL_CMD_MAP
        assert "科普" in _VERTICAL_CMD_MAP
        assert "故事" in _VERTICAL_CMD_MAP
        assert "奇闻" in _VERTICAL_CMD_MAP
        assert "观点" in _VERTICAL_CMD_MAP

    def test_help_text_has_new_commands(self):
        from api.webhooks import HELP_TEXT
        assert "解说" in HELP_TEXT
        assert "科普" in HELP_TEXT
        assert "故事" in HELP_TEXT
        assert "奇闻" in HELP_TEXT
        assert "观点" in HELP_TEXT
        assert "改写" in HELP_TEXT

    def test_run_vertical_function_exists(self):
        from api.webhooks import _run_vertical
        import inspect
        assert inspect.iscoroutinefunction(_run_vertical)

    def test_run_rewrite_function_exists(self):
        from api.webhooks import _run_rewrite
        import inspect
        assert inspect.iscoroutinefunction(_run_rewrite)


# ── voiceover.py 音色 ──

class TestVoiceoverPhase4:
    def test_narrator_male_exists(self):
        from layers.L4_audio.voiceover import VOICE_PRESETS
        assert "narrator_male" in VOICE_PRESETS

    def test_narrator_male_sharp_exists(self):
        from layers.L4_audio.voiceover import VOICE_PRESETS
        assert "narrator_male_sharp" in VOICE_PRESETS

    def test_narrator_female_calm_exists(self):
        from layers.L4_audio.voiceover import VOICE_PRESETS
        assert "narrator_female_calm" in VOICE_PRESETS

    def test_default_voice_is_narrator(self):
        from layers.L4_audio.voiceover import DEFAULT_VOICE
        assert DEFAULT_VOICE == "narrator_male"

    def test_all_presets_have_voice_type(self):
        from layers.L4_audio.voiceover import VOICE_PRESETS
        for key, preset in VOICE_PRESETS.items():
            assert "voice_type" in preset, f"{key} 缺少 voice_type"
            assert "name" in preset, f"{key} 缺少 name"
            assert "desc" in preset, f"{key} 缺少 desc"
