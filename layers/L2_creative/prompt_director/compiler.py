from __future__ import annotations

from dataclasses import dataclass

from layers.L2_creative.prompt_director.anchors import StoryAnchors, inject_anchors_into_prompt
from layers.L2_creative.prompt_director.schemas import (
    ModelPrompt,
    NarrativePlan,
    PromptDirectorPlan,
    ShotPlan,
    ShotType,
    UserIntent,
)


DEFAULT_NEGATIVE_CONSTRAINTS: tuple[str, ...] = (
    "不要乱码",
    "不要伪文字",
    "不要繁体招牌",
    "不要水印",
    "不要多余字幕",
    "不要扭曲手指",
    "不要面部变形",
    "不要品牌 logo",
)


@dataclass(frozen=True)
class SkillPromptPreset:
    shot_type: ShotType
    composition: str
    lighting: str
    camera_motion: str
    scene_texture: str
    prompt_tone: str


SKILL_PROMPT_PRESETS: dict[str, SkillPromptPreset] = {
    "cinematic_narrative": SkillPromptPreset(
        shot_type="medium_shot",
        composition="rule of thirds, clear subject silhouette",
        lighting="soft cinematic side light with realistic shadow falloff",
        camera_motion="slow push in, stable movement",
        scene_texture="cinematic real-world texture, subtle atmosphere, natural lens depth",
        prompt_tone="emotional cinematic storytelling",
    ),
    "douyin_viral": SkillPromptPreset(
        shot_type="close_up",
        composition="bold centered subject, high contrast foreground-background separation",
        lighting="bright punchy social-video lighting, clean highlights",
        camera_motion="quick but stable push in, no chaotic motion",
        scene_texture="high-retention short video look, vivid but clean",
        prompt_tone="viral hook, strong contrast, immediate visual impact",
    ),
    "wechat_real": SkillPromptPreset(
        shot_type="medium_shot",
        composition="natural handheld framing, everyday eye-level perspective",
        lighting="available natural light, soft indoor or street ambience",
        camera_motion="mostly static with slight handheld realism",
        scene_texture="real life documentary texture, not glossy, not overproduced",
        prompt_tone="restrained authentic life record",
    ),
    "product_ad": SkillPromptPreset(
        shot_type="detail_shot",
        composition="clean product-first composition, benefit point visually obvious",
        lighting="controlled commercial light, crisp edge highlight",
        camera_motion="slow product reveal, stable controlled motion",
        scene_texture="premium ad texture, clean surface, memorable visual cue",
        prompt_tone="product benefit, problem-solution, conversion oriented",
    ),
    "knowledge": SkillPromptPreset(
        shot_type="wide_shot",
        composition="clear explanatory composition, subject and context readable",
        lighting="clean neutral light, low visual noise",
        camera_motion="static or gentle lateral move, tutorial friendly",
        scene_texture="clear educational visual, simple examples, subtitle friendly",
        prompt_tone="structured explanation, intuitive example, calm authority",
    ),
}


def summarize_user_intent(intent: UserIntent) -> str:
    """Human-readable summary for logs and review messages."""
    notes = f"；补充：{'；'.join(intent.custom_notes)}" if intent.custom_notes else ""
    return (
        f"用户想法：{intent.raw_idea}\n"
        f"Skill：{intent.skill_name}（{intent.skill_id}）\n"
        f"情绪目标：{intent.audience_emotion}\n"
        f"主角/对象：{intent.subject_profile}\n"
        f"风格强度：{intent.style_intensity}{notes}"
    )


def build_narrative_plan(intent: UserIntent) -> NarrativePlan:
    """Create a deterministic story plan from the normalized user intent."""
    idea = _short_text(intent.raw_idea, 80)
    return NarrativePlan(
        hook=f"前 3 秒直接呈现「{idea}」最反直觉或最有情绪张力的一面。",
        emotional_arc=f"从{intent.subject_profile}的真实处境出发，逐步推动观众产生「{intent.audience_emotion}」。",
        conflict_or_turning_point="中段只设置一个清晰冲突或转折，避免在 5-10 秒内塞入多个连续动作。",
        ending_memory_point="结尾留下一个可复述的画面记忆点，而不是堆口号或屏幕文字。",
    )


def build_shot_plan(
    intent: UserIntent,
    *,
    clip_index: int,
    narration_segment: str,
) -> ShotPlan:
    """Build one clip-level visual plan. One clip gets one main action."""
    preset = _preset_for(intent.skill_id)
    action = _single_action_from_narration(narration_segment, intent)
    return ShotPlan(
        clip_index=clip_index,
        narration_segment=_short_text(str(narration_segment or intent.raw_idea), 120),
        shot_type=preset.shot_type,
        composition=preset.composition,
        lighting=_lighting_for_intensity(preset.lighting, intent.style_intensity),
        camera_motion=_motion_for_intensity(preset.camera_motion, intent.style_intensity),
        subject_action=action,
        scene_texture=preset.scene_texture,
    )


def compile_model_prompt(
    intent: UserIntent,
    narrative_plan: NarrativePlan,
    shot_plan: ShotPlan,
    *,
    prompt_budget: int = 2500,
) -> ModelPrompt:
    """Compile the P6.3 intermediate layer into provider-ready prompts."""
    preset = _preset_for(intent.skill_id)
    visual_parts = [
        f"{preset.prompt_tone}",
        f"theme: {intent.raw_idea}",
        f"subject: {intent.subject_profile}",
        f"audience emotion: {intent.audience_emotion}",
        f"shot: {shot_plan.shot_type}",
        f"composition: {shot_plan.composition}",
        f"lighting: {shot_plan.lighting}",
        f"scene texture: {shot_plan.scene_texture}",
        f"single main action: {shot_plan.subject_action}",
        f"memory point: {narrative_plan.ending_memory_point}",
        "realistic human anatomy, coherent face, clean background, no readable text",
    ]
    kling_parts = [
        f"stable {shot_plan.camera_motion}",
        f"one main action only: {shot_plan.subject_action}",
        f"keep character consistent as {intent.subject_profile}",
        "avoid fast cuts, avoid complex multi-step motion, preserve natural timing",
    ]
    negative_prompt = "，".join(DEFAULT_NEGATIVE_CONSTRAINTS)
    return ModelPrompt(
        visual_prompt=_trim_to_budget(", ".join(visual_parts), prompt_budget),
        kling_prompt=_trim_to_budget(", ".join(kling_parts), prompt_budget),
        negative_prompt=negative_prompt,
        prompt_budget=prompt_budget,
    )


def compile_prompt_director_plan(
    intent: UserIntent,
    *,
    clip_index: int = 1,
    narration_segment: str | None = None,
    prompt_budget: int = 2500,
) -> PromptDirectorPlan:
    """One-shot compiler: user intent -> four-layer P6.3 plan."""
    narration = str(narration_segment or intent.raw_idea).strip()
    narrative = build_narrative_plan(intent)
    shot = build_shot_plan(intent, clip_index=clip_index, narration_segment=narration)
    model_prompt = compile_model_prompt(intent, narrative, shot, prompt_budget=prompt_budget)
    return PromptDirectorPlan(
        user_intent=intent,
        narrative_plan=narrative,
        shot_plan=shot,
        model_prompt=model_prompt,
    )


def compile_clip_prompts(
    intent: UserIntent,
    narration_segments: list[str],
    *,
    prompt_budget: int = 2500,
    anchors: StoryAnchors | None = None,
) -> list[PromptDirectorPlan]:
    """Compile multiple clip narration segments into prompt director plans."""
    plans: list[PromptDirectorPlan] = []
    for idx, segment in enumerate(narration_segments, start=1):
        if not str(segment or "").strip():
            continue
        plan = compile_prompt_director_plan(
            intent,
            clip_index=idx,
            narration_segment=segment,
            prompt_budget=prompt_budget,
        )
        if anchors and (anchors.characters or anchors.scenes):
            model_prompt = plan.model_prompt.model_copy(
                update={
                    "visual_prompt": inject_anchors_into_prompt(plan.model_prompt.visual_prompt, anchors),
                    "kling_prompt": inject_anchors_into_prompt(plan.model_prompt.kling_prompt, anchors),
                }
            )
            plan = plan.model_copy(update={"model_prompt": model_prompt})
        plans.append(plan)
    return plans


def _preset_for(skill_id: str) -> SkillPromptPreset:
    return SKILL_PROMPT_PRESETS.get(skill_id, SKILL_PROMPT_PRESETS["douyin_viral"])


def _lighting_for_intensity(base: str, intensity: str) -> str:
    if intensity == "克制真实":
        return f"{base}, restrained realism, no glossy over-stylization"
    if intensity == "强风格化":
        return f"{base}, stronger contrast, more dramatic but still realistic"
    return base


def _motion_for_intensity(base: str, intensity: str) -> str:
    if intensity == "克制真实":
        return "mostly static, subtle natural movement"
    if intensity == "强风格化":
        return f"{base}, slightly stronger motion but no complex choreography"
    return base


def _single_action_from_narration(narration: str, intent: UserIntent) -> str:
    text = str(narration or "").strip()
    if not text:
        return f"{intent.subject_profile} holds a clear emotional beat"
    short = text[:48]
    return f"{intent.subject_profile} expresses one clear beat: {short}"


def _short_text(text: str, max_chars: int) -> str:
    text = str(text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max(1, max_chars - 1)].rstrip("，, ") + "…"


def _trim_to_budget(text: str, prompt_budget: int) -> str:
    budget = max(1, min(int(prompt_budget), 2500))
    text = str(text or "").strip()
    if len(text) <= budget:
        return text
    return text[: max(1, budget - 1)].rstrip("，, ") + "…"
