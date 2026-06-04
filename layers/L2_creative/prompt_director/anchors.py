"""D41-A Prompt anchors for multi-clip subject consistency.

The first clip is used to extract durable character/scene anchors. Later clip
prompts receive these anchors as hard visual constraints without changing the
existing storyboard generation flow.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from config.settings import get_settings
from core.langfuse_client import observe
from core.parsers import parse_json_object
from integrations.llm_client import get_deepseek

log = logging.getLogger(__name__)


class CharacterAnchor(BaseModel):
    """A persistent subject anchor for one storyboard."""

    name: str = Field(..., description="主体名/代号，如'苏宛'/'男主'/'红衣女子'")
    visual_description: str = Field(..., description="服装+发型+体型+饰品等视觉特征，20-60字")
    role: Literal["protagonist", "supporting", "narrator", "object", "setting"] = "protagonist"
    voice_traits: str = Field(default="", description="可选，旁白/对话相关")

    @field_validator("role", mode="before")
    @classmethod
    def _coerce_role(cls, v):
        """LLM tolerance: map Chinese/free-form role text back to enums."""
        if v is None:
            return "protagonist"
        s = str(v).strip().lower()
        if s in {"protagonist", "supporting", "narrator", "object", "setting"}:
            return s
        if any(k in s for k in ["主角", "主体", "主人公", "protag"]):
            return "protagonist"
        if any(k in s for k in ["配角", "辅", "support"]):
            return "supporting"
        if any(k in s for k in ["旁白", "叙述", "narrat"]):
            return "narrator"
        if any(k in s for k in ["道具", "物体", "object"]):
            return "object"
        if any(k in s for k in ["场景", "背景", "环境", "setting"]):
            return "setting"
        return "protagonist"


class SceneAnchor(BaseModel):
    """A persistent scene/environment anchor."""

    location: str = ""
    era: str = ""
    visual_style: str = Field(default="", description="如'胶片质感、冷色调、暗角'")


class StoryAnchors(BaseModel):
    """Storyboard-level anchors stored in storyboards.anchors JSONB."""

    characters: list[CharacterAnchor] = Field(default_factory=list)
    scenes: list[SceneAnchor] = Field(default_factory=list)
    extracted_from_clip_no: int = 1
    extracted_at: datetime = Field(default_factory=datetime.utcnow)


@observe(name="extract_anchors", as_type="generation")
async def extract_anchors_from_first_clip(
    clip_prompt: str,
    clip_narration: str,
    skill_name: str = "",
    *,
    storyboard_id: str | None = None,
) -> StoryAnchors:
    """Extract durable anchors from the first clip using the existing DeepSeek client.

    Failures return an empty StoryAnchors object so the video pipeline keeps
    running. The prompt asks the model to ignore one-off props and only capture
    subjects/scenes that should remain consistent across the full storyboard.
    """
    system_prompt = (
        "你是短视频多段一致性审片助手。请从第 1 段的视觉 prompt 和旁白里抽取贯穿全片的主体锚点和场景锚点。\n"
        "只抽会在后续多段持续出现的主角、旁白主体、核心场景和整体视觉调性。\n"
        "不要抽一次性道具、临时动作、转瞬即逝的画面元素。\n"
        "严格输出 JSON 对象，字段为 characters/scenes/extracted_from_clip_no。\n"
        "characters 每项包含 name, visual_description, role, voice_traits。\n"
        "role 字段必须严格使用以下 5 个英文枚举之一（不要写中文描述）："
        "protagonist（主角）/ supporting（配角）/ narrator（旁白叙述者）/ "
        "object（核心物体）/ setting（场景背景）。\n"
        "示例：{\"name\":\"苏宛\",\"visual_description\":\"红裙短发\",\"role\":\"protagonist\"}\n"
        "scenes 每项包含 location, era, visual_style。"
    )
    user_prompt = (
        f"skill_name: {skill_name}\n"
        f"clip_prompt:\n{clip_prompt}\n\n"
        f"clip_narration:\n{clip_narration}\n"
    )
    if storyboard_id:
        try:
            from langfuse.decorators import langfuse_context

            langfuse_context.update_current_observation(
                metadata={"storyboard_id": storyboard_id, "skill_name": skill_name}
            )
        except Exception:
            pass
    raw = ""
    try:
        response = await get_deepseek().chat.completions.create(
            model=get_settings().deepseek_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1200,
        )
        raw = response.choices[0].message.content or ""
        data = parse_json_object(raw)
        if not data:
            log.warning("[anchors] empty LLM response for first clip")
            return StoryAnchors()
        return StoryAnchors(**data)
    except Exception as exc:
        log.warning("[anchors] extract failed: %s. raw_response_head=%s", exc, raw[:200] if raw else "n/a")
        return StoryAnchors()


def inject_anchors_into_prompt(prompt: str, anchors: StoryAnchors) -> str:
    """Inject anchors into a provider prompt in an idempotent way."""
    if not anchors or (not anchors.characters and not anchors.scenes):
        return prompt

    out = str(prompt or "")
    scene_prefix = _format_scene_prefix(anchors)
    if scene_prefix and not out.startswith(scene_prefix):
        out = f"{scene_prefix}\n{out}" if out else scene_prefix

    for character in anchors.characters:
        name = character.name.strip()
        description = character.visual_description.strip()
        if not name or not description:
            continue
        if _description_present(out, description):
            continue
        pattern = re.compile(re.escape(name))
        out = pattern.sub(f"{name}（{description}）", out, count=1)
    return out


def _format_scene_prefix(anchors: StoryAnchors) -> str:
    parts: list[str] = []
    for scene in anchors.scenes:
        scene_parts = [p.strip() for p in (scene.location, scene.era, scene.visual_style) if p and p.strip()]
        if scene_parts:
            parts.append("，".join(scene_parts))
    if not parts:
        return ""
    return f"[场景：{'；'.join(parts)}]"


def _description_present(prompt: str, description: str) -> bool:
    """Return True when most major description tokens already exist in prompt."""
    if not prompt or not description:
        return False
    if description in prompt:
        return True
    desc_tokens = _keywords(description)
    if len(desc_tokens) < 4:
        return False
    if not desc_tokens:
        return False
    prompt_tokens = _keywords(prompt)
    overlap = len(desc_tokens & prompt_tokens)
    return overlap / len(desc_tokens) >= 0.60


def _keywords(text: str) -> set[str]:
    text = re.sub(r"[，。、“”‘’（）()【】\[\],.;:：；!！?？\s]+", " ", str(text or ""))
    words = {w.lower() for w in text.split() if len(w.strip()) >= 2}
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    words.update(cjk[i : i + 2] for i in range(max(0, len(cjk) - 1)))
    return {w for w in words if w.strip()}
