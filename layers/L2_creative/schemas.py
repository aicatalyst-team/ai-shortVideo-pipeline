from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from layers.L2_creative.character_manager import Position, list_characters
from layers.L2_creative.environment_manager import list_environments


WardrobeChoice = Literal["casual", "formal", "winter", "custom"]
SubjectEmotion = Literal[
    "neutral",
    "happy",
    "sad",
    "angry",
    "surprised",
    "thinking",
    "focused",
    "curious",
    "anxious",
    "calm",
]
TimeOfDay = Literal["morning", "noon", "afternoon", "evening", "night", "dawn", "dusk"]
CameraMovement = Literal[
    "static",
    "push_in",
    "pull_out",
    "pan_left",
    "pan_right",
    "tilt_up",
    "tilt_down",
    "track_left",
    "track_right",
    "handheld",
]
LightingMood = Literal[
    "natural",
    "warm",
    "cold",
    "dramatic",
    "soft",
    "hard",
    "golden",
    "neon",
]
Composition = Literal[
    "center",
    "rule_of_thirds",
    "symmetric",
    "leading_lines",
    "frame_within_frame",
    "negative_space",
]

# R2.1 改 30% (2026-05-20):
# voice_type 决定本镜配音模式。区分 narration/dialogue 对未来 R4 prompt 拼装
# 和 R7 接口选型（dialogue 走 HeyGen 类对口型，narration 走纯 TTS）至关重要。
# 不加这个字段，下游永远分不清"旁白"和"角色台词"，画面驴唇不对马嘴。
VoiceType = Literal["narration", "dialogue", "ambient", "silent"]


# Phase P Sprint P2：按视频段时长卡 narration 字数硬上限（中文朗读约 7-8 字/秒）
# 5/10s 档对应飞书发抖音视频实测：超 40/82 字必然产生 >1.2s 音画漂移（P1 hard_fail）
# 字数 = len(narration_segment)（含中英文/标点/数字，不算前后空格）
_NARRATION_CHAR_LIMITS_BY_DURATION: list[tuple[float, int]] = [
    # (duration_sec 上限, 字数硬上限)
    (2.5, 20),
    (4.5, 30),
    (7.5, 40),  # 5s 主档
    (9.5, 60),
    (15.0, 82),  # 10s 主档（覆盖 estimated_duration_sec le=15 全范围）
]


def get_narration_char_limit(duration_sec: float) -> int:
    """根据 estimated_duration_sec 查表返回 narration 字数硬上限。"""
    for upper, limit in _NARRATION_CHAR_LIMITS_BY_DURATION:
        if duration_sec <= upper:
            return limit
    # duration > 15s 理论上 schema le=15 已挡，兜底返回最大值
    return _NARRATION_CHAR_LIMITS_BY_DURATION[-1][1]


class SceneShot(BaseModel):
    """Single storyboard shot. R2.1 strong schema."""

    model_config = {"extra": "forbid"}

    scene_no: int = Field(..., ge=1)

    narration_segment: str = Field(..., min_length=1, max_length=200)
    estimated_duration_sec: float = Field(..., gt=0, le=15)

    character_id: str = Field(..., description="Must exist in characters.yaml")
    environment_id: str = Field(..., description="Must exist in environments.yaml")
    time_of_day: TimeOfDay

    subject_action: str = Field(..., min_length=1, max_length=200)
    subject_emotion: SubjectEmotion
    wardrobe_choice: WardrobeChoice = "casual"
    outfit_override: str = Field(default="", max_length=200)
    key_props: list[str] = Field(default_factory=list, max_length=8)

    position: Position = Field(default_factory=Position)
    camera_movement: CameraMovement = "static"

    lighting_mood: LightingMood
    composition: Composition = "center"

    # R2.1 改 30%: 本镜配音模式（narration=旁白 / dialogue=角色台词需对口型 / ambient=仅环境音 / silent=静默）
    voice_type: VoiceType = "narration"

    @field_validator("character_id")
    @classmethod
    def _check_character(cls, v: str) -> str:
        valid_ids = [c.key for c in list_characters()]
        if v not in valid_ids:
            raise ValueError(f"character_id '{v}' is not in characters.yaml; available: {valid_ids}")
        return v

    @field_validator("environment_id")
    @classmethod
    def _check_environment(cls, v: str) -> str:
        valid_ids = [e.key for e in list_environments()]
        if v not in valid_ids:
            raise ValueError(f"environment_id '{v}' is not in environments.yaml; available: {valid_ids}")
        return v

    @model_validator(mode="after")
    def _check_outfit(self) -> "SceneShot":
        if self.wardrobe_choice == "custom" and not self.outfit_override.strip():
            raise ValueError("outfit_override is required when wardrobe_choice='custom'")
        if self.wardrobe_choice != "custom" and self.outfit_override:
            raise ValueError("outfit_override must be empty when wardrobe_choice is not 'custom'")
        return self

    @model_validator(mode="after")
    def _check_narration_length_vs_duration(self) -> "SceneShot":
        """Phase P P2：narration 字数必须匹配 estimated_duration_sec（防音画漂移）。"""
        text = (self.narration_segment or "").strip()
        char_count = len(text)
        limit = get_narration_char_limit(self.estimated_duration_sec)
        if char_count > limit:
            raise ValueError(
                f"narration_segment 字数 {char_count} 超过 {self.estimated_duration_sec:.1f}s 片段上限 {limit} 字。"
                f"请压缩到 {limit} 字以内（中文朗读约 7-8 字/秒）。"
                f"当前文本：{text[:50]}..."
            )
        return self


class Storyboard(BaseModel):
    """Complete storyboard. One video maps to one Storyboard."""

    model_config = {"extra": "forbid"}

    plan_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=100)
    theme: str = Field(..., min_length=1, max_length=200)
    style_name: str = Field(..., min_length=1)
    main_character_id: str
    total_duration_sec: float = Field(..., gt=0, le=120)
    # R2.1 改 30%: 抖音短视频平均 30-60s = 5-8 shots，max 12 留太多余量。
    # 收紧到 10，强迫 LLM 浓缩节奏（短视频信息密度高于电影感）。
    shots: list[SceneShot] = Field(..., min_length=1, max_length=10)

    @field_validator("main_character_id")
    @classmethod
    def _check_main(cls, v: str) -> str:
        valid_ids = [c.key for c in list_characters()]
        if v not in valid_ids:
            raise ValueError(f"main_character_id '{v}' is not in characters.yaml; available: {valid_ids}")
        return v

    @model_validator(mode="after")
    def _check_continuity(self) -> "Storyboard":
        nos = [s.scene_no for s in self.shots]
        expected = list(range(1, len(nos) + 1))
        if nos != expected:
            raise ValueError(f"scene_no must be continuous from 1, got {nos}, expected {expected}")

        total = sum(s.estimated_duration_sec for s in self.shots)
        if abs(total - self.total_duration_sec) > 2.0:
            raise ValueError(
                f"total_duration_sec({self.total_duration_sec}) differs from shot total({total:.2f}) by more than 2s"
            )

        char_ids = {s.character_id for s in self.shots}
        if self.main_character_id not in char_ids:
            raise ValueError(f"main_character_id={self.main_character_id} does not appear in any shot")

        # R2.2 改 30% (2026-05-20):
        # 镜头多样性硬约束。原本只在 chains_v2 system prompt 里软约束（"相邻不能相同"），
        # 但 LLM 偷懒时仍会全 medium。schema 层强制后，违规直接 ValidationError → 自动重试。
        # 规则：≥5 shots 时至少 2 种 camera_distance；≥8 shots 时至少 3 种。
        # 短片（<5 shots）不卡，给 LLM 灵活度。
        if len(self.shots) >= 5:
            distances = [s.position.camera_distance for s in self.shots]
            unique_count = len(set(distances))
            min_unique = 3 if len(self.shots) >= 8 else 2
            if unique_count < min_unique:
                raise ValueError(
                    f"shots 镜头景别过于单一: {distances}，至少需要 {min_unique} 种不同 camera_distance"
                )

        return self


# ── R2.2 / R2.3 incremental schemas ─────────────────────────────────────────


class SchemaValidationError(Exception):
    """Raised when LLM output still violates Storyboard schema after retries."""

    def __init__(self, attempts: int, last_error: str, last_raw: str = ""):
        self.attempts = attempts
        self.last_error = last_error
        self.last_raw = last_raw
        super().__init__(f"LLM output violated schema after {attempts} attempts: {last_error}")


ScoreDimension = Literal["hook", "narrative", "visual", "rhythm", "potential"]


class DimensionScore(BaseModel):
    model_config = {"extra": "forbid"}

    dimension: ScoreDimension
    score: int = Field(..., ge=0, le=100)
    reason: str = Field(..., min_length=1, max_length=300)


class ScoreReport(BaseModel):
    """R2.3 evaluation output: five-dimension score plus verdict."""

    model_config = {"extra": "forbid"}

    storyboard_plan_id: str
    overall_score: float = Field(..., ge=0, le=100)
    dimension_scores: list[DimensionScore] = Field(..., min_length=5, max_length=5)
    strengths: list[str] = Field(default_factory=list, max_length=5)
    improvements: list[str] = Field(default_factory=list, max_length=5)
    verdict: Literal["pass", "needs_revision", "fail"]

    @model_validator(mode="after")
    def _check_dimensions_complete(self) -> "ScoreReport":
        dims = {d.dimension for d in self.dimension_scores}
        expected = {"hook", "narrative", "visual", "rhythm", "potential"}
        if dims != expected:
            raise ValueError(f"dimension_scores must cover all 5 dimensions; missing: {expected - dims}")
        return self
