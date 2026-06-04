from __future__ import annotations

import pytest


def test_sanitize_visual_prompt_removes_hud_and_panel_triggers():
    from layers.L3_visual.prompt_safety import sanitize_visual_prompt

    prompt = (
        "beautiful young woman in futuristic lab, holographic HUD overlay, "
        "transparent data panel, screen text TOONHENY, chart labels, 1080P"
    )

    safe = sanitize_visual_prompt(prompt)
    lowered = safe.lower()
    positive = lowered.split("premium cinematic scene", 1)[0]

    for banned in [
        "hud",
        "holographic",
        "transparent data panel",
        "screen text",
        "toonheny",
        "chart labels",
        "1080p",
    ]:
        assert banned not in positive
    assert "no readable text" in lowered
    assert "no gibberish letters" in lowered


def test_style_suffix_is_sanitized_after_enrichment():
    from layers.L2_creative.style_engine import get_template
    from layers.L3_visual.prompt_safety import sanitize_visual_prompt

    style = get_template("cyberpunk_military")
    enriched = style.enrich_image_prompt(
        "portrait in lab with floating panel and analysis text"
    )
    safe = sanitize_visual_prompt(enriched)
    lowered = safe.lower()

    assert "floating panel" not in lowered
    assert "analysis text" not in lowered
    assert "holographic hud" not in lowered
    assert "no readable text" in lowered


def test_stronger_textless_prompt_does_not_duplicate_guard_and_stays_bounded():
    from layers.L3_visual.image_to_video import _PROMPT_MAX_LEN, _stronger_textless_prompt
    from layers.L3_visual.prompt_safety import TEXTLESS_VISUAL_GUARD, sanitize_visual_prompt

    base = sanitize_visual_prompt("young woman in tech launch event with product branding")
    stronger = _stronger_textless_prompt(base)

    assert len(stronger) <= _PROMPT_MAX_LEN
    assert stronger.count(TEXTLESS_VISUAL_GUARD) == 1


def test_fit_visual_prompt_preserves_primary_semantics_under_budget():
    from layers.L3_visual.prompt_safety import TEXTLESS_VISUAL_GUARD_SHORT, fit_visual_prompt, sanitize_visual_prompt

    prompt = sanitize_visual_prompt(
        ", ".join(
            [
                "young founder giving keynote on a clean stage",
                "calm confident expression",
                "close-up portrait framing",
                "warm studio lighting",
                "premium cinematic details",
                "product branding on the backdrop",
                "transparent data panel nearby",
                "clean highlights",
                "subtle quality cue",
                "alternative angle perspective",
            ]
        )
    )

    fitted = fit_visual_prompt(prompt, max_len=220)

    assert len(fitted) <= 220
    assert "young founder giving keynote on a clean stage" in fitted
    assert "close-up portrait framing" in fitted
    assert TEXTLESS_VISUAL_GUARD_SHORT in fitted


def test_parse_visual_review_commands():
    from api.webhooks import _parse_visual_review_command

    assert _parse_visual_review_command("1.继续") == ("continue", "")
    assert _parse_visual_review_command("2.重新生成: 右侧太空，人物太小") == (
        "regenerate",
        "右侧太空，人物太小",
    )
    assert _parse_visual_review_command("3.取消: 选题方向不对") == ("cancel", "选题方向不对")


def test_video_artifact_inspection_requires_multiple_weak_frame_hits(tmp_path, monkeypatch):
    import layers.L3_visual.image_to_video as pipeline

    frames = [str(tmp_path / f"frame_{idx:03d}.jpg") for idx in range(1, 4)]
    for frame in frames:
        open(frame, "wb").close()

    weak_report = type(
        "Report",
        (),
        {
            "has_artifacts": True,
            "artifact_type": "fake_ui_label",
            "confidence": 0.86,
            "evidence": "small unclear label-like marks",
            "reason": "possible fake UI label",
        },
    )
    clean_report = type(
        "Report",
        (),
        {"has_artifacts": False, "artifact_type": "none", "confidence": 0.0, "evidence": "", "reason": ""},
    )
    reports = [weak_report(), clean_report(), clean_report()]

    monkeypatch.setattr(pipeline, "extract_frames", lambda *args, **kwargs: frames)
    monkeypatch.setattr(pipeline, "inspect_text_artifacts", lambda path: reports.pop(0))

    assert pipeline._inspect_video_text_artifacts("clip.mp4") is None


@pytest.mark.anyio
async def test_generate_clip_sanitizes_final_image_and_video_prompts(tmp_path, monkeypatch):
    import layers.L3_visual.image_to_video as pipeline
    from layers.L2_creative.style_engine import get_template
    from layers.L3_visual.providers.base import ImageResult, VideoResult

    captured: dict[str, str] = {}

    async def fake_generate_image(**kwargs):
        captured["image_prompt"] = kwargs["prompt"]
        captured["negative_prompt"] = kwargs["negative_prompt"]
        return ImageResult(url="file://first.png", local_path=kwargs["output_path"], model="fake")

    async def fake_image_to_video(**kwargs):
        captured["kling_prompt"] = kwargs["prompt"]
        return VideoResult(url="file://clip.mp4", local_path=kwargs["output_path"], model="fake")

    monkeypatch.setattr(pipeline, "generate_image", fake_generate_image)
    monkeypatch.setattr(pipeline, "image_to_video", fake_image_to_video)
    monkeypatch.setattr(
        pipeline,
        "inspect_text_artifacts",
        lambda path: type("Report", (), {"has_artifacts": False, "reason": ""})(),
    )
    monkeypatch.setattr(pipeline, "_inspect_video_text_artifacts", lambda path: None)

    await pipeline.generate_clip(
        image_prompt="futuristic lab with holographic HUD overlay and TOONHENY text",
        kling_prompt="camera moves across transparent data panel with screen text",
        output_path=str(tmp_path / "clip.mp4"),
        style=get_template("cyberpunk_military"),
    )

    image_prompt = captured["image_prompt"].lower()
    kling_prompt = captured["kling_prompt"].lower()
    image_positive = image_prompt.split("premium cinematic scene", 1)[0]
    kling_positive = kling_prompt.split("premium cinematic scene", 1)[0]

    for banned in ["hud", "holographic", "toonheny", "transparent data panel", "screen text"]:
        assert banned not in image_positive
        assert banned not in kling_positive
    assert "gibberish text" in captured["negative_prompt"].lower()
    assert "fake ui" in captured["negative_prompt"].lower()


@pytest.mark.anyio
async def test_generate_clip_retries_when_first_frame_has_text_artifacts(tmp_path, monkeypatch):
    import layers.L3_visual.image_to_video as pipeline
    from layers.L2_creative.style_engine import get_template
    from layers.L3_visual.providers.base import ImageResult, VideoResult

    image_prompts: list[str] = []

    async def fake_generate_image(**kwargs):
        image_prompts.append(kwargs["prompt"])
        return ImageResult(url="file://first.png", local_path=kwargs["output_path"], model="fake")

    async def fake_image_to_video(**kwargs):
        return VideoResult(url="file://clip.mp4", local_path=kwargs["output_path"], model="fake")

    reports = [
        type("Report", (), {"has_artifacts": True, "reason": "garbled letters"})(),
        type("Report", (), {"has_artifacts": False, "reason": ""})(),
    ]

    monkeypatch.setattr(pipeline, "generate_image", fake_generate_image)
    monkeypatch.setattr(pipeline, "image_to_video", fake_image_to_video)
    monkeypatch.setattr(pipeline, "inspect_text_artifacts", lambda path: reports.pop(0))
    monkeypatch.setattr(pipeline, "_inspect_video_text_artifacts", lambda path: None)

    await pipeline.generate_clip(
        image_prompt="premium cyberpunk portrait with abstract geometric overlay",
        kling_prompt="slow cinematic camera movement",
        output_path=str(tmp_path / "clip.mp4"),
        style=get_template("cyberpunk_military"),
    )

    assert len(image_prompts) == 1


@pytest.mark.anyio
async def test_generate_clip_treats_sampled_frame_artifacts_as_advisory(tmp_path, monkeypatch):
    import layers.L3_visual.image_to_video as pipeline
    from layers.L2_creative.style_engine import get_template
    from layers.L3_visual.providers.base import ImageResult, VideoResult

    image_prompts: list[str] = []
    video_prompts: list[str] = []

    async def fake_generate_image(**kwargs):
        image_prompts.append(kwargs["prompt"])
        return ImageResult(url="file://first.png", local_path=kwargs["output_path"], model="fake")

    async def fake_image_to_video(**kwargs):
        video_prompts.append(kwargs["prompt"])
        return VideoResult(url="file://clip.mp4", local_path=kwargs["output_path"], model="fake")

    reports = [
        type("Report", (), {"has_artifacts": True, "reason": "fake logo on shirt", "frame_path": "frame_001.jpg"})(),
    ]

    monkeypatch.setattr(pipeline, "generate_image", fake_generate_image)
    monkeypatch.setattr(pipeline, "image_to_video", fake_image_to_video)
    monkeypatch.setattr(
        pipeline,
        "inspect_text_artifacts",
        lambda path: type("Report", (), {"has_artifacts": False, "reason": ""})(),
    )
    monkeypatch.setattr(pipeline, "_inspect_video_text_artifacts", lambda path: reports.pop(0))

    await pipeline.generate_clip(
        image_prompt="young woman in tech launch event with product branding",
        kling_prompt="camera moves past a premium presentation stage",
        output_path=str(tmp_path / "clip.mp4"),
        style=get_template("cyberpunk_military"),
        first_frame_path=None,
    )

    assert len(image_prompts) == 1
    assert len(video_prompts) == 1


@pytest.mark.anyio
async def test_generate_clip_does_not_fail_when_video_artifacts_persist(tmp_path, monkeypatch):
    import layers.L3_visual.image_to_video as pipeline
    from layers.L2_creative.style_engine import get_template
    from layers.L3_visual.providers.base import ImageResult, VideoResult

    async def fake_generate_image(**kwargs):
        return ImageResult(url="file://first.png", local_path=kwargs["output_path"], model="fake")

    async def fake_image_to_video(**kwargs):
        return VideoResult(url="file://clip.mp4", local_path=kwargs["output_path"], model="fake")

    monkeypatch.setattr(pipeline, "generate_image", fake_generate_image)
    monkeypatch.setattr(pipeline, "image_to_video", fake_image_to_video)
    monkeypatch.setattr(
        pipeline,
        "inspect_text_artifacts",
        lambda path: type("Report", (), {"has_artifacts": False, "reason": ""})(),
    )
    monkeypatch.setattr(
        pipeline,
        "_inspect_video_text_artifacts",
        lambda path: type("Report", (), {"has_artifacts": True, "reason": "garbled brand text", "frame_path": "frame_001.jpg"})(),
    )

    result = await pipeline.generate_clip(
        image_prompt="brand keynote stage",
        kling_prompt="luxury product presentation close-up",
        output_path=str(tmp_path / "clip.mp4"),
        style=get_template("cyberpunk_military"),
    )

    assert result.local_path == str(tmp_path / "clip.mp4")


def test_caption_text_is_normalized_to_simplified():
    from api.webhooks import _build_timed_captions_from_text
    from layers.L5_postprod.captions import _trim_caption_text

    items = _build_timed_captions_from_text("這個視頻裡的畫面錯亂", 4.0)
    assert items
    assert "這" not in "".join(i.text for i in items)
    assert "视频" in "".join(i.text for i in items)
    assert _trim_caption_text("這個視頻") == "这个视频"
