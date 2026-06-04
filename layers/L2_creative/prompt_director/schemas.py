from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


QuestionId = Literal["audience_emotion", "subject_profile", "style_intensity"]
StyleIntensity = Literal["克制真实", "标准增强", "强风格化"]
ShotType = Literal["close_up", "medium_shot", "wide_shot", "detail_shot"]


class QuestionOption(BaseModel):
    """A lightweight user-facing option for Prompt Director questions."""

    value: str
    label: str
    description: str = ""
    is_default: bool = False


class DirectorQuestion(BaseModel):
    """One restrained follow-up question shown before storyboard generation."""

    id: QuestionId
    title: str
    prompt: str
    options: list[QuestionOption] = Field(default_factory=list)
    default_value: str


class PromptDirectorAnswers(BaseModel):
    """Normalized answers after applying Skill defaults and free-form fallbacks."""

    audience_emotion: str
    subject_profile: str
    style_intensity: StyleIntensity
    custom_notes: list[str] = Field(default_factory=list)


class UserIntent(BaseModel):
    """P6.2 user intent layer before the full P6.3 intermediate schema lands."""

    raw_idea: str
    skill_id: str
    skill_name: str
    audience_emotion: str
    subject_profile: str
    style_intensity: StyleIntensity
    custom_notes: list[str] = Field(default_factory=list)


class NarrativePlan(BaseModel):
    """Story-level intent distilled from the user idea and selected Skill."""

    hook: str = Field(..., min_length=1, max_length=240)
    emotional_arc: str = Field(..., min_length=1, max_length=240)
    conflict_or_turning_point: str = Field(..., min_length=1, max_length=240)
    ending_memory_point: str = Field(..., min_length=1, max_length=240)


class ShotPlan(BaseModel):
    """Clip-level visual plan used as the only prompt compiler input."""

    clip_index: int = Field(..., ge=1)
    narration_segment: str = Field(..., min_length=1, max_length=120)
    shot_type: ShotType
    composition: str = Field(..., min_length=1, max_length=120)
    lighting: str = Field(..., min_length=1, max_length=160)
    camera_motion: str = Field(..., min_length=1, max_length=120)
    subject_action: str = Field(..., min_length=1, max_length=160)
    scene_texture: str = Field(..., min_length=1, max_length=160)


class ModelPrompt(BaseModel):
    """Compiled provider prompt bundle."""

    visual_prompt: str = Field(..., min_length=1, max_length=2500)
    kling_prompt: str = Field(..., min_length=1, max_length=2500)
    negative_prompt: str = Field(..., min_length=1, max_length=1200)
    prompt_budget: int = Field(default=2500, gt=0, le=2500)


class PromptDirectorPlan(BaseModel):
    """P6.3 four-layer intermediate representation."""

    user_intent: UserIntent
    narrative_plan: NarrativePlan
    shot_plan: ShotPlan
    model_prompt: ModelPrompt
