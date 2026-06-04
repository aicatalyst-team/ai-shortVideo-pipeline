from __future__ import annotations

import json
from types import SimpleNamespace
from typing import get_args

import pytest

from layers.L2_creative.prompt_director import anchors as anchors_module
from layers.L2_creative.prompt_director.anchors import (
    CharacterAnchor,
    SceneAnchor,
    StoryAnchors,
    extract_anchors_from_first_clip,
    inject_anchors_into_prompt,
)
from layers.L2_creative.prompt_director.compiler import compile_clip_prompts
from layers.L2_creative.prompt_director.schemas import StyleIntensity, UserIntent


class _FakeCompletions:
    def __init__(self, content: str | None = None, exc: Exception | None = None):
        self.content = content
        self.exc = exc

    async def create(self, **_kwargs):
        if self.exc:
            raise self.exc
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class _FakeDeepSeek:
    def __init__(self, content: str | None = None, exc: Exception | None = None):
        self.chat = SimpleNamespace(completions=_FakeCompletions(content, exc))


def _anchors() -> StoryAnchors:
    return StoryAnchors(
        characters=[
            CharacterAnchor(
                name="苏宛",
                visual_description="红色连衣裙、利落短发、银色耳环、身形纤细",
                role="protagonist",
            )
        ],
        scenes=[
            SceneAnchor(location="雨夜天桥", era="现代都市", visual_style="冷色调、胶片颗粒、轻微暗角")
        ],
    )


def _intent() -> UserIntent:
    return UserIntent(
        raw_idea="苏宛在雨夜讲述 AI 创业故事",
        skill_id="douyin_viral",
        skill_name="抖音爆款",
        audience_emotion="紧张又好奇",
        subject_profile="苏宛",
        style_intensity=get_args(StyleIntensity)[1],
    )


@pytest.mark.asyncio
async def test_extract_anchors_from_first_clip_returns_storyanchors_with_character(monkeypatch):
    payload = {
        "characters": [
            {
                "name": "苏宛",
                "visual_description": "红色连衣裙、利落短发、银色耳环、身形纤细",
                "role": "protagonist",
                "voice_traits": "冷静克制",
            }
        ],
        "scenes": [{"location": "雨夜天桥", "era": "现代都市", "visual_style": "冷色调"}],
        "extracted_from_clip_no": 1,
    }
    monkeypatch.setattr(
        anchors_module,
        "get_deepseek",
        lambda: _FakeDeepSeek(json.dumps(payload, ensure_ascii=False)),
    )

    result = await extract_anchors_from_first_clip("苏宛站在雨夜天桥", "苏宛开始讲述")

    assert isinstance(result, StoryAnchors)
    assert len(result.characters) == 1
    assert result.characters[0].name == "苏宛"


def test_inject_anchors_appends_description_to_first_character_name():
    prompt = "苏宛站在雨夜天桥，苏宛看向镜头"

    result = inject_anchors_into_prompt(prompt, _anchors())

    assert "苏宛（红色连衣裙、利落短发、银色耳环、身形纤细）站在" in result
    assert result.count("红色连衣裙") == 1


def test_inject_anchors_is_idempotent_and_does_not_repeat_on_second_call():
    prompt = "苏宛站在雨夜天桥，苏宛看向镜头"

    once = inject_anchors_into_prompt(prompt, _anchors())
    twice = inject_anchors_into_prompt(once, _anchors())

    assert once == twice
    assert twice.count("红色连衣裙") == 1


def test_scene_anchor_prefix_is_added_to_prompt_start():
    result = inject_anchors_into_prompt("苏宛看向镜头", _anchors())

    assert result.startswith("[场景：雨夜天桥，现代都市，冷色调、胶片颗粒、轻微暗角]\n")


def test_empty_anchors_returns_original_prompt():
    prompt = "苏宛看向镜头"

    assert inject_anchors_into_prompt(prompt, StoryAnchors()) == prompt


def test_description_present_requires_high_overlap_to_skip():
    """Loose similarity should not skip anchor injection."""
    anchors = StoryAnchors(
        characters=[
            CharacterAnchor(
                name="苏宛",
                visual_description="红色连衣裙、利落短发、银色耳环",
                role="protagonist",
            )
        ]
    )
    prompt = "苏宛穿红色卫衣站着"

    result = inject_anchors_into_prompt(prompt, anchors)

    assert "红色连衣裙、利落短发、银色耳环" in result


def test_description_present_high_overlap_skips_injection():
    """A direct full description substring should remain idempotent."""
    anchors = StoryAnchors(
        characters=[
            CharacterAnchor(
                name="苏宛",
                visual_description="红色连衣裙、利落短发、银色耳环、纤细身形",
                role="protagonist",
            )
        ]
    )
    prompt = "苏宛穿红色连衣裙、利落短发、银色耳环、纤细身形走在天桥"

    result = inject_anchors_into_prompt(prompt, anchors)

    assert result.count("红色连衣裙") == 1


def test_character_anchor_coerces_chinese_role_description():
    c = CharacterAnchor(name="苏宛", visual_description="红裙", role="核心主体，类比LLM的推理者")

    assert c.role == "protagonist"


def test_character_anchor_coerces_unknown_role_to_protagonist():
    c = CharacterAnchor(name="x", visual_description="y", role="完全不认识的字符串")

    assert c.role == "protagonist"


def test_character_anchor_accepts_canonical_english_enum():
    c = CharacterAnchor(name="x", visual_description="y", role="supporting")

    assert c.role == "supporting"


def test_compile_clip_prompts_with_anchors_vs_without_anchors():
    without = compile_clip_prompts(_intent(), ["苏宛走上天桥"])
    with_anchors = compile_clip_prompts(_intent(), ["苏宛走上天桥"], anchors=_anchors())

    assert without[0].model_prompt.visual_prompt != with_anchors[0].model_prompt.visual_prompt
    assert "红色连衣裙" not in without[0].model_prompt.visual_prompt
    assert "红色连衣裙" in with_anchors[0].model_prompt.visual_prompt
    assert with_anchors[0].model_prompt.visual_prompt.startswith("[场景：")


@pytest.mark.asyncio
async def test_extract_anchors_returns_empty_storyanchors_when_llm_fails(monkeypatch):
    monkeypatch.setattr(
        anchors_module,
        "get_deepseek",
        lambda: _FakeDeepSeek(exc=RuntimeError("llm down")),
    )

    result = await extract_anchors_from_first_clip("prompt", "narration")

    assert isinstance(result, StoryAnchors)
    assert result.characters == []
    assert result.scenes == []


@pytest.mark.asyncio
async def test_extract_anchors_accepts_storyboard_id_kwarg(monkeypatch):
    """The new storyboard_id kwarg is backward compatible."""
    payload = {
        "characters": [{"name": "x", "visual_description": "abcd efgh", "role": "protagonist"}],
        "scenes": [],
        "extracted_from_clip_no": 1,
    }
    monkeypatch.setattr(
        anchors_module,
        "get_deepseek",
        lambda: _FakeDeepSeek(json.dumps(payload, ensure_ascii=False)),
    )

    r1 = await extract_anchors_from_first_clip("p", "n")
    r2 = await extract_anchors_from_first_clip("p", "n", storyboard_id="sb_123")

    assert isinstance(r1, StoryAnchors)
    assert isinstance(r2, StoryAnchors)
    assert r1.characters == r2.characters
