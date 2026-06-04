"""Sprint 3 tests: VL critic + append-only memory gate."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_critic_engine_imports_and_format():
    from layers.L7_optimization.critic_engine import (
        VLCriticScore,
        VL_CRITIC_PASS_THRESHOLD,
        MAX_REGEN_ATTEMPTS,
        format_vl_critic_report,
        should_regenerate,
    )

    assert VL_CRITIC_PASS_THRESHOLD == 70
    assert MAX_REGEN_ATTEMPTS == 1
    score = VLCriticScore(
        total=62,
        passed=False,
        dimensions={"visual_realism": 55, "shot_diversity": 60},
        issues=["画面塑料感明显"],
        suggestions=["增加真实光影和胶片噪点"],
        should_regenerate=True,
        frames_analyzed=6,
    )
    msg = format_vl_critic_report(score)
    assert "VL 成片质检" in msg
    assert "画面塑料感" in msg
    assert should_regenerate(score, 0) is True
    assert should_regenerate(score, 1) is False


def test_critic_engine_invalid_response_is_not_fake_sixty():
    from layers.L7_optimization.critic_engine import (
        _invalid_score,
        format_vl_critic_report,
        should_regenerate,
    )

    score = _invalid_score(
        frames_analyzed=6,
        raw="",
        error="GLM-4V 未返回任何文本内容",
    )
    msg = format_vl_critic_report(score)
    assert score.valid is False
    assert score.total == 0
    assert score.should_regenerate is False
    assert should_regenerate(score, 0) is False
    assert "VL 成片质检未完成" in msg
    assert "60/100" not in msg


def test_critic_engine_retries_strict_prompt(monkeypatch, tmp_path):
    from PIL import Image
    import layers.L7_optimization.critic_engine as ce

    frames = []
    for idx in range(2):
        path = tmp_path / f"frame_{idx}.jpg"
        Image.new("RGB", (320, 568), "white").save(path)
        frames.append(path)

    calls = []

    def fake_call_glm4v_multi(image_paths, prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return ""
        return (
            '{"character_consistency":70,"visual_realism":68,'
            '"shot_diversity":72,"caption_sync":66,"publish_readiness":70,'
            '"issues":["字幕偏小"],"suggestions":["放大字幕"],"should_regenerate":false}'
        )

    monkeypatch.setattr(ce, "extract_video_keyframes", lambda video_path, frame_count=6: frames)
    monkeypatch.setattr(ce, "call_glm4v_multi", fake_call_glm4v_multi)

    score = ce.score_video_with_vl("dummy.mp4")
    assert score.valid is True
    assert len(calls) == 2
    assert "Return ONLY one valid JSON object" in calls[1]
    assert "Do NOT transcribe/OCR" in calls[1]


def test_critic_engine_retries_non_numeric_scores(monkeypatch, tmp_path):
    from PIL import Image
    import layers.L7_optimization.critic_engine as ce

    frame = tmp_path / "frame.jpg"
    Image.new("RGB", (320, 568), "white").save(frame)
    calls = []

    def fake_call_glm4v_multi(image_paths, prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return '{"character_consistency":"looks consistent","visual_realism":70,"shot_diversity":70,"caption_sync":70,"publish_readiness":70,"issues":[],"suggestions":[],"should_regenerate":"false"}'
        return '{"character_consistency":70,"visual_realism":70,"shot_diversity":70,"caption_sync":70,"publish_readiness":70,"issues":[],"suggestions":[],"should_regenerate":"false"}'

    monkeypatch.setattr(ce, "extract_video_keyframes", lambda video_path, frame_count=6: [frame])
    monkeypatch.setattr(ce, "call_glm4v_multi", fake_call_glm4v_multi)

    score = ce.score_video_with_vl("dummy.mp4")
    assert score.valid is True
    assert score.should_regenerate is False
    assert len(calls) == 2


def test_glm4v_grid_preserves_portrait_aspect(tmp_path):
    from PIL import Image
    from integrations.llm_client import _make_frame_grid

    frames = []
    for idx in range(6):
        path = tmp_path / f"portrait_{idx}.jpg"
        Image.new("RGB", (360, 640), "white").save(path)
        frames.append(path)

    grid = _make_frame_grid(frames)
    try:
        with Image.open(grid) as img:
            assert img.size == (1080, 1280)
    finally:
        grid.unlink(missing_ok=True)


def test_call_glm4v_multi_keeps_task_prompt_before_grid_note(monkeypatch, tmp_path):
    from PIL import Image
    import integrations.llm_client as client

    frame = tmp_path / "frame.jpg"
    Image.new("RGB", (360, 640), "white").save(frame)
    seen = {}

    def fake_call(path, prompt):
        seen["prompt"] = prompt
        return "{}"

    monkeypatch.setattr(client, "_call_glm4v_api", fake_call)

    client.call_glm4v_multi([frame], "Return ONLY JSON")

    assert seen["prompt"].startswith("Return ONLY JSON")
    assert "【网格图说明】" in seen["prompt"]


def test_vl_prompt_forbids_ocr_and_requires_json():
    from layers.L7_optimization.critic_engine import _build_vl_prompt

    prompt = _build_vl_prompt(
        narration="旁白",
        style_name="hot_news_commentary",
        caption_sample="字幕",
    )
    strict = _build_vl_prompt(
        narration="旁白",
        style_name="hot_news_commentary",
        caption_sample="字幕",
        strict=True,
    )

    assert "禁止 OCR" in prompt
    assert "回复必须以 { 开头" in prompt
    assert "Do NOT transcribe/OCR" in strict
    assert "MUST start with {" in strict


def test_memory_file_has_required_markers():
    path = Path(__file__).resolve().parent.parent / "config" / "LONG_TERM_MEMORY.md"
    text = path.read_text(encoding="utf-8")
    assert "<!-- HANDWRITTEN_PERMANENT_END -->" in text
    assert "<!-- AI_APPROVED_APPEND_ONLY -->" in text
    assert text.count("\n") > 10


def test_dreaming_scheduler_append_only(tmp_path):
    from core.dreaming_scheduler import (
        AI_MARKER,
        MemoryProposal,
        append_approved_memory,
        ensure_long_term_memory,
        read_generation_memory,
    )

    path = tmp_path / "LONG_TERM_MEMORY.md"
    ensure_long_term_memory(path)
    before = path.read_text(encoding="utf-8")
    handwritten = before.split(AI_MARKER)[0]
    proposal = MemoryProposal(
        id="TEST1234",
        style_name="hot_news_commentary",
        insight="高完播内容更早给结论",
        evidence="avg_completion=0.42",
        prompt_rule="热搜解说在前 5 秒先给结论，再补背景。",
        confidence=0.8,
    )
    append_approved_memory(proposal, path)
    after = path.read_text(encoding="utf-8")
    assert after.split(AI_MARKER)[0] == handwritten
    assert "热搜解说在前 5 秒先给结论" in after
    assert isinstance(read_generation_memory(120), str)


def test_webhook_sprint3_commands_present():
    from api.webhooks import HELP_TEXT, _handle_light_command
    import inspect

    assert "记忆提炼" in HELP_TEXT
    assert "记忆通过" in HELP_TEXT
    assert inspect.iscoroutinefunction(_handle_light_command)


def test_video_generation_prompts_are_sanitized():
    from api.webhooks import (
        _build_timed_captions_from_text,
        _normalize_camera_control,
        _safe_visual_prompt,
        _shot_map_from_visual,
        _shot_template_map,
    )

    prompt = _safe_visual_prompt("手机屏幕上出现'睡前1小时'倒计时提示 12:00")
    assert "睡前1小时" not in prompt
    assert "12:00" not in prompt
    assert "no readable text" in prompt

    brand_prompt = _safe_visual_prompt(
        "Google search page showing Apple Mac logo, AI bar chart labels and 1080P text"
    )
    lowered = brand_prompt.lower()
    assert "google" not in lowered
    assert "apple" not in lowered
    assert " mac " not in f" {lowered} "
    assert "logo" in lowered  # only appears in the negative guard
    assert "bar chart" not in lowered
    assert "1080p" not in lowered
    assert " ai " not in f" {lowered} "
    assert "pseudo text" in lowered
    assert "mirrored text" in lowered

    zh_prompt = _safe_visual_prompt("谷歌搜索页面对比图，左侧10条蓝色链接，右侧AI摘要框")
    assert "谷歌" not in zh_prompt
    assert "搜索页面" not in zh_prompt
    assert "链接" not in zh_prompt
    assert "10" not in zh_prompt

    shots = _shot_map_from_visual({"shots": [{"shot_no": 2, "image_prompt": "wide shot"}]})
    assert shots[2]["image_prompt"] == "wide shot"

    template_shots = _shot_template_map("hot_news_commentary")
    assert template_shots[1]["camera_control"]["type"] == "push_in"

    camera = _normalize_camera_control({"type": "pan_right", "config": {"horizontal": 50, "vertical": 0, "zoom": "bad"}})
    assert camera == {"type": "pan_right", "config": {"horizontal": 10, "vertical": 0, "zoom": 0}}
    assert _normalize_camera_control({"type": "bad", "config": {}}) is None

    items = _build_timed_captions_from_text("第一句很长很长很长，第二句也很长。", 6.0)
    assert len(items) >= 2
    assert all(len(item.text) <= 15 for item in items)


def test_caption_fallback_uses_narration_not_visual_keywords():
    from api.webhooks import _build_timed_captions_from_text

    narration = "咖啡涨价让很多年轻人开始重新计算每天的预算。"
    visual_caption = "价格暴涨"

    items = _build_timed_captions_from_text(narration, 6.0)

    assert items
    joined = "".join(item.text for item in items)
    assert "年轻人" in joined
    assert visual_caption not in [item.text for item in items]
