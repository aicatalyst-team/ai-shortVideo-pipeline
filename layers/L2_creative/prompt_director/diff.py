"""Phase P Sprint P7.3: apply review hints as single-dimension prompt patches."""
from __future__ import annotations

import logging
from typing import Callable

from layers.L2_creative.prompt_director.schemas import PromptDirectorPlan

log = logging.getLogger(__name__)

PatcherFn = Callable[[PromptDirectorPlan], PromptDirectorPlan]


def _patch_closer_shot(plan: PromptDirectorPlan) -> PromptDirectorPlan:
    new_shot = plan.shot_plan.model_copy(update={"shot_type": "close_up"})
    return plan.model_copy(update={"shot_plan": new_shot})


def _patch_wider_shot(plan: PromptDirectorPlan) -> PromptDirectorPlan:
    new_shot = plan.shot_plan.model_copy(update={"shot_type": "wide_shot"})
    return plan.model_copy(update={"shot_plan": new_shot})


def _patch_more_realistic(plan: PromptDirectorPlan) -> PromptDirectorPlan:
    new_texture = plan.shot_plan.scene_texture + ", restrained realism, documentary-like, not over-stylized"
    new_shot = plan.shot_plan.model_copy(update={"scene_texture": new_texture})
    return plan.model_copy(update={"shot_plan": new_shot})


def _patch_more_dramatic(plan: PromptDirectorPlan) -> PromptDirectorPlan:
    new_shot = plan.shot_plan.model_copy(
        update={
            "scene_texture": plan.shot_plan.scene_texture + ", stronger contrast, dramatic mood",
            "lighting": plan.shot_plan.lighting + ", more dramatic chiaroscuro",
        }
    )
    return plan.model_copy(update={"shot_plan": new_shot})


def _patch_no_text(plan: PromptDirectorPlan) -> PromptDirectorPlan:
    prefix = "绝对不要任何文字, 绝对不要字幕, 绝对不要 logo, 绝对不要乱码, "
    new_model = plan.model_prompt.model_copy(
        update={"negative_prompt": prefix + plan.model_prompt.negative_prompt}
    )
    return plan.model_copy(update={"model_prompt": new_model})


def _patch_brighter(plan: PromptDirectorPlan) -> PromptDirectorPlan:
    new_shot = plan.shot_plan.model_copy(
        update={"lighting": plan.shot_plan.lighting + ", brighter exposure, clean highlights"}
    )
    return plan.model_copy(update={"shot_plan": new_shot})


def _patch_darker(plan: PromptDirectorPlan) -> PromptDirectorPlan:
    new_shot = plan.shot_plan.model_copy(
        update={"lighting": plan.shot_plan.lighting + ", low-key moody lighting, deeper shadow"}
    )
    return plan.model_copy(update={"shot_plan": new_shot})


def _patch_warmer_tone(plan: PromptDirectorPlan) -> PromptDirectorPlan:
    new_shot = plan.shot_plan.model_copy(
        update={"lighting": plan.shot_plan.lighting + ", warm color tone, golden hour feel"}
    )
    return plan.model_copy(update={"shot_plan": new_shot})


def _patch_cooler_tone(plan: PromptDirectorPlan) -> PromptDirectorPlan:
    new_shot = plan.shot_plan.model_copy(
        update={"lighting": plan.shot_plan.lighting + ", cool blue color tone, slight teal cast"}
    )
    return plan.model_copy(update={"shot_plan": new_shot})


def _patch_more_motion(plan: PromptDirectorPlan) -> PromptDirectorPlan:
    new_shot = plan.shot_plan.model_copy(
        update={"camera_motion": plan.shot_plan.camera_motion + ", more pronounced but still stable movement"}
    )
    return plan.model_copy(update={"shot_plan": new_shot})


def _patch_static_shot(plan: PromptDirectorPlan) -> PromptDirectorPlan:
    new_shot = plan.shot_plan.model_copy(
        update={"camera_motion": "fully static camera, no movement at all"}
    )
    return plan.model_copy(update={"shot_plan": new_shot})


def _patch_different_character(plan: PromptDirectorPlan) -> PromptDirectorPlan:
    log.warning(
        "[prompt_diff] hint=different_character can only be noted at prompt layer; "
        "ask user to switch character_id explicitly"
    )
    note = "用户想换主角（请用户重新选 character_id；prompt 层只能提示，无法真换）"
    new_intent = plan.user_intent.model_copy(
        update={"custom_notes": [*plan.user_intent.custom_notes, note]}
    )
    return plan.model_copy(update={"user_intent": new_intent})


def _patch_different_scene(plan: PromptDirectorPlan) -> PromptDirectorPlan:
    log.warning("[prompt_diff] hint=different_scene can only hint; environment_id is unchanged")
    note = "用户想换场景（请用户重新选 environment_id）"
    new_shot = plan.shot_plan.model_copy(
        update={"scene_texture": plan.shot_plan.scene_texture + ", alternative scene setting"}
    )
    new_intent = plan.user_intent.model_copy(
        update={"custom_notes": [*plan.user_intent.custom_notes, note]}
    )
    return plan.model_copy(update={"shot_plan": new_shot, "user_intent": new_intent})


_HINT_PATCHERS: dict[str, PatcherFn] = {
    "closer_shot": _patch_closer_shot,
    "wider_shot": _patch_wider_shot,
    "more_realistic": _patch_more_realistic,
    "more_dramatic": _patch_more_dramatic,
    "no_text": _patch_no_text,
    "brighter": _patch_brighter,
    "darker": _patch_darker,
    "warmer_tone": _patch_warmer_tone,
    "cooler_tone": _patch_cooler_tone,
    "more_motion": _patch_more_motion,
    "static_shot": _patch_static_shot,
    "different_character": _patch_different_character,
    "different_scene": _patch_different_scene,
}


def prompt_diff_for_regenerate(
    plan: PromptDirectorPlan,
    hints: list[str],
    *,
    custom_notes: list[str] | None = None,
) -> PromptDirectorPlan:
    """Patch a compiled plan with P4 review hints without recompiling it."""
    current = plan.model_copy(deep=True)

    for hint in hints or []:
        patcher = _HINT_PATCHERS.get(hint)
        if patcher is None:
            log.warning("[prompt_diff] unknown hint=%r skipped", hint)
            continue
        current = patcher(current)
        log.info("[prompt_diff] applied hint=%s", hint)

    extra_notes = [note.strip() for note in (custom_notes or []) if note and note.strip()]
    if extra_notes:
        existing = list(current.user_intent.custom_notes)
        merged = existing + [note for note in extra_notes if note not in existing]
        new_intent = current.user_intent.model_copy(update={"custom_notes": merged})
        current = current.model_copy(update={"user_intent": new_intent})

    return current


def list_supported_hints() -> list[str]:
    """Return all P7.3 supported hint keys."""
    return sorted(_HINT_PATCHERS.keys())
