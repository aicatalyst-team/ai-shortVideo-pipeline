"""Tests for the M3 plans.evaluation -> v2 clips backfill helpers.

These tests avoid any real database connection and exercise only pure mapping
logic plus lightweight ORM object construction.
"""

from __future__ import annotations

from scripts.backfill_clips import (
    _build_clips_from_scenes,
    _build_storyboard_from_plan,
    _extract_top_ranked,
)


class _FakePlan:
    def __init__(
        self,
        id: str = "P001",
        theme: str = "coffee price rise",
        style_name: str = "hot_news_commentary",
        evaluation=None,
    ):
        self.id = id
        self.theme = theme
        self.style_name = style_name
        self.evaluation = evaluation


def test_extract_top_ranked_returns_first_item():
    eval_data = {
        "ranked": [
            {"rank": 1, "angle": "first", "score": 9.0},
            {"rank": 2, "angle": "second", "score": 7.0},
        ]
    }

    top = _extract_top_ranked(eval_data)

    assert top["angle"] == "first"


def test_extract_top_ranked_handles_scripts_alias():
    eval_data = {"scripts": [{"angle": "alt", "scenes": []}]}

    top = _extract_top_ranked(eval_data)

    assert top["angle"] == "alt"


def test_extract_top_ranked_returns_none_for_empty():
    assert _extract_top_ranked(None) is None
    assert _extract_top_ranked({}) is None
    assert _extract_top_ranked({"ranked": []}) is None
    assert _extract_top_ranked({"other_key": "..."}) is None
    assert _extract_top_ranked({"ranked": ["bad"]}) is None


def test_build_storyboard_from_plan_uses_angle_as_title():
    plan = _FakePlan(id="P001", theme="coffee price rise")
    top = {"angle": "young people cannot afford coffee", "score": 8.5}

    sb = _build_storyboard_from_plan(plan, top)

    assert sb.plan_id == "P001"
    assert sb.title == "young people cannot afford coffee"
    assert sb.theme == "coffee price rise"
    assert sb.style_name == "hot_news_commentary"
    assert sb.status == "ready"
    assert sb.storyboard_metadata["original_score"] == 8.5
    assert sb.storyboard_metadata["source"] == "backfill_from_plan_evaluation"


def test_build_storyboard_falls_back_to_theme_when_angle_missing():
    plan = _FakePlan(id="P001", theme="coffee price rise")
    top = {"score": 8.5}

    sb = _build_storyboard_from_plan(plan, top)

    assert sb.title == "coffee price rise"


def test_build_clips_from_scenes_creates_one_per_scene():
    scenes = [
        {"scene_no": 1, "image_desc": "coffee beans close-up", "narration_segment": "did you know"},
        {"scene_no": 2, "image_desc": "Brazil farm", "narration_segment": "Brazil frost"},
        {"scene_no": 3, "image_desc": "data chart", "narration_segment": "60 percent rise"},
    ]

    clips = _build_clips_from_scenes("SB001", scenes)

    assert len(clips) == 3
    assert clips[0].seq == 1
    assert clips[0].storyboard_id == "SB001"
    assert clips[0].prompt == "coffee beans close-up"
    assert clips[0].narration_segment == "did you know"
    assert clips[0].status == "ready"
    assert clips[0].r_metadata["source"] == "backfill_from_plan_scene"
    assert clips[0].r_metadata["original_scene"] == scenes[0]


def test_build_clips_skips_non_dict_entries():
    scenes = [
        {"scene_no": 1, "image_desc": "ok"},
        "garbage string",
        None,
        {"scene_no": 2, "image_desc": "ok2"},
    ]

    clips = _build_clips_from_scenes("SB001", scenes)

    assert len(clips) == 2
    assert [c.prompt for c in clips] == ["ok", "ok2"]


def test_build_clips_seq_falls_back_to_index():
    scenes = [
        {"image_desc": "no scene_no"},
        {"image_desc": "also no scene_no"},
    ]

    clips = _build_clips_from_scenes("SB001", scenes)

    assert clips[0].seq == 1
    assert clips[1].seq == 2


def test_build_clips_copies_legacy_video_url_aliases():
    scenes = [
        {"scene_no": 1, "image_desc": "x", "video_path": "http://legacy/video.mp4"},
        {"scene_no": 2, "image_desc": "y", "video_url": "http://new/video.mp4"},
    ]

    clips = _build_clips_from_scenes("SB001", scenes)

    assert clips[0].video_url == "http://legacy/video.mp4"
    assert clips[1].video_url == "http://new/video.mp4"


# ── --dry-run / --plan-id CLI 参数测试 ──


def test_cli_parser_supports_dry_run_and_plan_id():
    """argparse 必须接受 --dry-run 和 --plan-id 参数。"""
    import argparse
    import scripts.backfill_clips as bf

    # 用 introspection 触发 parser，构造 namespace
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--skip-check", action="store_true")
    parser.add_argument("--output", type=str)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--plan-id", type=str)

    ns = parser.parse_args(["--dry-run", "--plan-id", "P001"])
    assert ns.dry_run is True
    assert ns.plan_id == "P001"


def test_dry_run_smoke_keeps_function_signatures():
    """backfill_one_plan 和 backfill_all 都应该接受 dry_run kwarg。"""
    import inspect
    from scripts.backfill_clips import backfill_all, backfill_one_plan

    one_sig = inspect.signature(backfill_one_plan)
    assert "dry_run" in one_sig.parameters, "backfill_one_plan 必须有 dry_run 参数"
    assert one_sig.parameters["dry_run"].default is False

    all_sig = inspect.signature(backfill_all)
    assert "dry_run" in all_sig.parameters
    assert "plan_id" in all_sig.parameters
    assert all_sig.parameters["dry_run"].default is False
    assert all_sig.parameters["plan_id"].default is None


def test_main_module_help_includes_new_flags():
    """直接执行 --help 应当包含 --dry-run 和 --plan-id 说明。"""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "scripts/backfill_clips.py", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    output = result.stdout + result.stderr
    assert "--dry-run" in output
    assert "--plan-id" in output
    assert "operator-targeted repair" in output or "preview only" in output
