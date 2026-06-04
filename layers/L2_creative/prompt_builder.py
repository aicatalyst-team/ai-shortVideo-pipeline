"""4: five-element structured image prompt builder."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from config.settings import get_settings
from layers.L2_creative.character_manager import CharacterProfile, get_character
from layers.L2_creative.environment_manager import EnvironmentProfile, get_environment
from layers.L2_creative.schemas import SceneShot
from layers.L2_creative.style_engine import StyleTemplate

log = logging.getLogger(__name__)


SHOT_TYPE_DESC = {
    "extreme_close": "extreme close-up, face fills the entire frame",
    "close_up": "close-up shot, face fills the entire frame",
    "medium_close": "medium close-up, chest up",
    "medium": "medium shot, waist up",
    "medium_wide": "medium wide shot, full body in context",
    "wide": "wide establishing shot, full body with environment",
    "extreme_wide": "extreme wide shot, tiny figure in vast scene",
    "over_shoulder": "over-the-shoulder shot, third-person view",
}

ANGLE_DESC = {
    "eye_level": "eye-level angle, natural and balanced",
    "low_angle": "low angle shot from below, conveys power",
    "high_angle": "high angle shot from above, conveys vulnerability",
    "dutch": "dutch angle, tilted camera for tension",
    "birds_eye": "bird's-eye view, directly overhead",
    "worms_eye": "worm's-eye view, looking straight up",
}

LIGHTING_DESC = {
    "natural": "natural lighting, soft and balanced",
    "warm": "warm golden lighting, cozy atmosphere",
    "cold": "cold blue lighting, sterile or melancholic",
    "dramatic": "dramatic chiaroscuro lighting, strong shadows",
    "soft": "soft diffused lighting, flattering and gentle",
    "hard": "hard direct lighting, sharp shadows",
    "golden": "golden hour lighting, magical warm glow",
    "neon": "neon cyberpunk lighting, vibrant pink and cyan",
}

COMPOSITION_DESC = {
    "center": "centered composition, subject in middle",
    "rule_of_thirds": "rule of thirds composition, subject off-center",
    "symmetric": "symmetric composition, balanced left-right",
    "leading_lines": "leading lines guide eye to subject",
    "frame_within_frame": "frame within frame composition",
    "negative_space": "minimal composition with negative space",
}

VOICE_TYPE_HINT = {
    "narration": "subject not looking at camera, focused on action",
    "dialogue": "subject facing camera, lips visible for lip-sync",
    "ambient": "subject in environment, no direct attention",
    "silent": "subject still, atmospheric mood",
}

QUALITY_TAIL = "masterpiece, best quality, ultra detailed, 8k, photorealistic"


# R5 改 30% (2026-05-20):
# 智能 negative_prompt 生成。Kling 文生图支持 negative_prompt（generate_image 参数已有）
# 但 prompt_builder 完全没用上 → 模型仍可能生成"低质量/构图错位/光线错"的图。
# 从 shot 字段反推 negative 词，主动告诉模型"不要"什么 → 配合 positive prompt 双向约束。
NEGATIVE_BASE = (
    "low quality, blurry, deformed, distorted face, extra limbs, "
    "bad anatomy, watermark, signature, text overlay, readable text, "
    "letters, numbers, logo, brand mark, pseudo text, gibberish letters, "
    "mirrored text, reversed text, chart labels"
)

LIGHTING_OPPOSITE = {
    "warm": "cold blue tones, harsh shadows",
    "cold": "warm orange tones, soft glow",
    "soft": "harsh hard light, deep shadows",
    "hard": "soft diffused glow, no contrast",
    "dramatic": "flat even lighting",
    "natural": "artificial neon, studio strobes",
    "golden": "blue hour, twilight purple",
    "neon": "natural daylight, muted colors",
}

COMPOSITION_OPPOSITE = {
    "symmetric": "off-center, unbalanced framing",
    "center": "subject on the edge, cropped awkwardly",
    "rule_of_thirds": "subject dead center, static framing",
    "leading_lines": "chaotic random lines",
    "frame_within_frame": "no foreground, flat composition",
    "negative_space": "cluttered background, busy distracting",
}

VOICE_TYPE_NEGATIVE = {
    # narration: 主体不应直视镜头
    "narration": "subject staring at camera, breaking the fourth wall",
    # dialogue: 主体必须直视，反例是侧脸/背对
    "dialogue": "subject facing away, profile only, mouth covered or out of frame",
    # ambient: 不要特写主体
    "ambient": "tight portrait close-up, subject dominates frame",
    # silent: 不要动态/对白姿态
    "silent": "open mouth talking, exaggerated gestures, dynamic action",
}


def _resolve_wardrobe(character: CharacterProfile, shot: SceneShot) -> str:
    if shot.wardrobe_choice == "custom":
        return shot.outfit_override
    wardrobe = character.wardrobe
    return getattr(wardrobe, shot.wardrobe_choice, "") or wardrobe.casual or ""


def _build_subject_block(character: CharacterProfile, shot: SceneShot) -> str:
    parts = []
    if character.appearance.face:
        parts.append(character.appearance.face)
    if character.appearance.hair:
        parts.append(character.appearance.hair)
    outfit = _resolve_wardrobe(character, shot)
    if outfit:
        parts.append(f"wearing {outfit}")
    return ", ".join(parts) if parts else character.display_name


def _build_action_block(shot: SceneShot) -> str:
    voice_hint = VOICE_TYPE_HINT.get(shot.voice_type, "")
    parts = [shot.subject_action, f"{shot.subject_emotion} expression"]
    if shot.key_props:
        parts.append(f"with {', '.join(shot.key_props)}")
    if voice_hint:
        parts.append(voice_hint)
    return ", ".join(parts)


def _build_environment_block(env: EnvironmentProfile, shot: SceneShot) -> str:
    parts = [f"in {env.display_name}"]
    if env.props:
        parts.append(f"with {', '.join(env.props[:3])}")
    parts.append(f"{shot.time_of_day} time")
    return ", ".join(parts)


def _build_framing_block(shot: SceneShot) -> str:
    parts = [
        SHOT_TYPE_DESC.get(shot.position.camera_distance, shot.position.camera_distance),
        ANGLE_DESC.get(shot.position.camera_angle, shot.position.camera_angle),
        COMPOSITION_DESC.get(shot.composition, shot.composition),
    ]
    if shot.camera_movement != "static":
        parts.append(f"camera {shot.camera_movement.replace('_', ' ')}")
    return ", ".join(parts)


def _build_lighting_block(shot: SceneShot) -> str:
    return LIGHTING_DESC.get(shot.lighting_mood, f"{shot.lighting_mood} lighting")


def _build_style_block(style: StyleTemplate) -> str:
    return getattr(style, "visual_keywords", None) or style.visual_style or "high quality photography"


def _load_shot_template_v2(style_name: str) -> list[dict]:
    cfg = get_settings()
    path = Path(cfg.style_templates_dir).parent / "shot_templates" / f"{style_name}.yaml"
    if not path.exists():
        log.warning("[shot_template] %s not found", path)
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("shots", []) or []


_SHOT_TEMPLATE_CACHE: dict[str, list[dict]] = {}


def get_shot_hints(style_name: str) -> list[dict]:
    if style_name not in _SHOT_TEMPLATE_CACHE:
        _SHOT_TEMPLATE_CACHE[style_name] = _load_shot_template_v2(style_name)
    return _SHOT_TEMPLATE_CACHE[style_name]


def pick_shot_hint(style_name: str, shot: SceneShot, total_shots: int) -> str:
    hints = get_shot_hints(style_name)
    if not hints:
        return ""

    if shot.scene_no == 1:
        return hints[0].get("prompt_hint", "")
    if shot.scene_no == total_shots:
        return hints[-1].get("prompt_hint", "")

    middle_hints = hints[1:-1] if len(hints) > 2 else hints
    idx = (shot.scene_no - 2) % len(middle_hints) if middle_hints else 0
    return middle_hints[idx].get("prompt_hint", "")


# R5 改 30%: 智能 negative_prompt 生成
def build_negative_prompt(shot: SceneShot, extra: str = "") -> str:
    """根据 shot 字段反推 negative_prompt（告诉模型"不要什么"）。

    与 positive prompt 双向约束。Kling/SDXL 等模型 negative_prompt 对画面质量提升 ~15-25%。

    Args:
        shot: R2 SceneShot 实例
        extra: 额外 negative 词追加
    """
    parts = [NEGATIVE_BASE]

    lighting_neg = LIGHTING_OPPOSITE.get(shot.lighting_mood)
    if lighting_neg:
        parts.append(lighting_neg)

    composition_neg = COMPOSITION_OPPOSITE.get(shot.composition)
    if composition_neg:
        parts.append(composition_neg)

    voice_neg = VOICE_TYPE_NEGATIVE.get(shot.voice_type)
    if voice_neg:
        parts.append(voice_neg)

    if extra:
        parts.append(extra)

    return ", ".join(parts)


def build_image_prompt(
    shot: SceneShot,
    style: StyleTemplate,
    *,
    character: CharacterProfile | None = None,
    env: EnvironmentProfile | None = None,
    total_shots: int = 0,
    extra_modifiers: str = "",
) -> str:
    """Build subject + action + environment + framing + lighting + style prompt."""
    if character is None:
        character = get_character(shot.character_id)
        if character is None:
            raise ValueError(f"character_id {shot.character_id} not found in R1 assets")
    if env is None:
        env = get_environment(shot.environment_id)
        if env is None:
            raise ValueError(f"environment_id {shot.environment_id} not found in R1 assets")

    blocks = [
        _build_subject_block(character, shot),
        _build_action_block(shot),
        _build_environment_block(env, shot),
        _build_framing_block(shot),
        _build_lighting_block(shot),
        _build_style_block(style),
        QUALITY_TAIL,
    ]

    if total_shots > 0:
        hint = pick_shot_hint(style.name, shot, total_shots)
        if hint:
            blocks.insert(-1, hint)

    if extra_modifiers:
        blocks.append(extra_modifiers)

    prompt = ", ".join(b for b in blocks if b)
    log.debug("[prompt_builder] shot=%d prompt=%s...", shot.scene_no, prompt[:120])
    return prompt
