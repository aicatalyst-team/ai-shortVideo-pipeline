"""
Phase 1 集成测试
测试风格模板引擎、配置管理、内容安全、JSON解析、管线结构。
不测试外部 API 调用（需 mock）。
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── config/settings.py ──

class TestSettings:
    def test_defaults(self):
        from config.settings import Settings
        s = Settings(
            deepseek_api_key="test",
            glm_api_key="test",
            kling_access_key="test",
            kling_secret_key="test",
        )
        assert s.deepseek_base_url == "https://api.deepseek.com/v1"
        assert s.kling_cost_5s == 0.35
        assert s.max_concurrent_jobs == 1
        assert "政治" in s.blocked_keywords

    def test_ensure_dirs(self, tmp_path):
        from config.settings import Settings
        s = Settings(data_dir=tmp_path / "data", output_dir=tmp_path / "output")
        s.ensure_dirs()
        assert (tmp_path / "data").is_dir()
        assert (tmp_path / "output").is_dir()


# ── core/guard.py ──

class TestContentGuard:
    def test_pass(self):
        from core.guard import content_guard
        ok, reason = content_guard("猫猫上班的搞笑视频")
        assert ok is True
        assert reason == "通过"

    def test_block(self):
        from core.guard import content_guard
        ok, reason = content_guard("涉及政治敏感话题")
        assert ok is False
        assert "政治" in reason


# ── core/parsers.py ──

class TestParsers:
    def test_parse_json_array_clean(self):
        from core.parsers import parse_json_array
        result = parse_json_array('[{"a": 1}, {"a": 2}]')
        assert len(result) == 2
        assert result[0]["a"] == 1

    def test_parse_json_array_markdown_wrapped(self):
        from core.parsers import parse_json_array
        raw = '```json\n[{"x": "hello"}]\n```'
        result = parse_json_array(raw)
        assert len(result) == 1
        assert result[0]["x"] == "hello"

    def test_parse_json_array_invalid(self):
        from core.parsers import parse_json_array
        result = parse_json_array("not json at all")
        assert result == []

    def test_parse_json_object(self):
        from core.parsers import parse_json_object
        result = parse_json_object('some text {"key": "val"} more text')
        assert result["key"] == "val"

    def test_parse_json_object_invalid(self):
        from core.parsers import parse_json_object
        result = parse_json_object("nope")
        assert result == {}


# ── layers/L2_creative/style_engine.py ──

class TestStyleEngine:
    def test_load_templates(self):
        from layers.L2_creative.style_engine import load_all_templates
        templates = load_all_templates(force=True)
        assert len(templates) >= 4
        assert "cyberpunk_military" in templates
        assert "cute_healing" in templates
        assert "funny_comedy" in templates
        assert "hot_blooded" in templates

    def test_template_system_prompt(self):
        from layers.L2_creative.style_engine import get_template
        tpl = get_template("cyberpunk_military")
        prompt = tpl.system_prompt()
        assert "风格档案" in prompt
        assert "赛博朋克" in prompt
        assert tpl.aspect_ratio == "9:16"

    def test_template_enrich_prompt(self):
        from layers.L2_creative.style_engine import get_template
        tpl = get_template("cyberpunk_military")
        enriched = tpl.enrich_image_prompt("a cat soldier")
        assert "cyberpunk" in enriched.lower()
        assert "a cat soldier" in enriched

    def test_get_nonexistent_template(self):
        from layers.L2_creative.style_engine import get_template
        with pytest.raises(KeyError):
            get_template("nonexistent_style")

    def test_list_template_names(self):
        from layers.L2_creative.style_engine import list_template_names
        names = list_template_names()
        assert isinstance(names, list)
        assert len(names) >= 4


# ── layers/L3_visual/providers/base.py ──

class TestBaseProviders:
    def test_image_result(self):
        from layers.L3_visual.providers.base import ImageResult
        r = ImageResult(url="https://example.com/img.png", local_path="/tmp/img.png")
        assert r.url.startswith("https://")

    def test_video_result(self):
        from layers.L3_visual.providers.base import VideoResult
        r = VideoResult(url="https://example.com/vid.mp4", duration_sec=10, task_id="abc")
        assert r.duration_sec == 10


# ── layers/L2_creative/chains.py (structure only, no API calls) ──

class TestChainsStructure:
    def test_format_evaluation(self):
        from layers.L2_creative.chains import format_evaluation
        evaluation = {
            "plans": [
                {
                    "script_index": 1,
                    "operator": "苏晚",
                    "total_duration_sec": 15,
                    "clips": [
                        {"clip_no": 1, "duration_sec": 5, "scene_summary": "开场", "reason": "快节奏"},
                        {"clip_no": 2, "duration_sec": 10, "scene_summary": "主体", "reason": "信息量大"},
                    ],
                    "quality": "standard",
                    "quality_reason": "日常场景",
                }
            ]
        }
        msg, cost = format_evaluation(evaluation)
        assert "苏晚" in msg
        assert "方案1" in msg
        assert cost > 0


# ── 项目结构验证 ──

class TestProjectStructure:
    EXPECTED_DIRS = [
        "config", "config/style_templates",
        "core", "layers",
        "layers/L1_trending", "layers/L2_creative",
        "layers/L3_visual", "layers/L3_visual/providers",
        "layers/L4_audio", "layers/L5_postprod",
        "layers/L6_distribution",
        "layers/L7_optimization",
        "integrations", "db", "api", "tests",
    ]

    def test_directories_exist(self):
        root = Path(__file__).resolve().parent.parent
        for d in self.EXPECTED_DIRS:
            assert (root / d).is_dir(), f"目录缺失: {d}"

    def test_init_files_exist(self):
        root = Path(__file__).resolve().parent.parent
        for d in self.EXPECTED_DIRS:
            init = root / d / "__init__.py"
            assert init.exists(), f"缺少 __init__.py: {d}"

    def test_style_templates_exist(self):
        root = Path(__file__).resolve().parent.parent
        tpl_dir = root / "config" / "style_templates"
        yamls = list(tpl_dir.glob("*.yaml"))
        assert len(yamls) >= 4, f"风格模板不足4个: {[y.name for y in yamls]}"
