from __future__ import annotations

from collections.abc import Mapping

from layers.L2_creative.creative_skills import CreativeSkillConfig
from layers.L2_creative.prompt_director.schemas import (
    DirectorQuestion,
    PromptDirectorAnswers,
    QuestionOption,
    StyleIntensity,
    UserIntent,
)


DEFAULT_MARKERS = {"", "默认", "不填", "随便", "都行", "无", "none", "default"}
STYLE_INTENSITY_VALUES: set[str] = {"克制真实", "标准增强", "强风格化"}

EMOTION_OPTIONS: list[QuestionOption] = [
    QuestionOption(value="被鼓舞", label="被鼓舞", description="适合成长、品牌故事、技术进步"),
    QuestionOption(value="被治愈", label="被治愈", description="适合生活感、陪伴感、温柔叙事"),
    QuestionOption(value="被震撼", label="被震撼", description="适合发布会、大片感、强视觉冲击"),
    QuestionOption(value="想转发", label="想转发", description="适合热点、观点、反差话题"),
    QuestionOption(value="想购买/咨询", label="想购买/咨询", description="适合产品广告和转化目标"),
    QuestionOption(value="自定义", label="自定义", description="用户自己描述情绪目标"),
]

SUBJECT_OPTIONS: list[QuestionOption] = [
    QuestionOption(value="普通上班族", label="普通上班族"),
    QuestionOption(value="创业者/技术人", label="创业者/技术人"),
    QuestionOption(value="年轻女性", label="年轻女性"),
    QuestionOption(value="年轻男性", label="年轻男性"),
    QuestionOption(value="产品/品牌", label="产品/品牌"),
    QuestionOption(value="上传参考图", label="上传参考图"),
    QuestionOption(value="自定义", label="自定义"),
]

INTENSITY_OPTIONS: list[QuestionOption] = [
    QuestionOption(value="克制真实", label="克制真实", description="更像真实生活记录，不油腻"),
    QuestionOption(value="标准增强", label="标准增强", description="有明显电影感，但不过度炫技"),
    QuestionOption(value="强风格化", label="强风格化", description="更像广告片/爆款短片，视觉冲击更强"),
]


def build_director_questions(skill: CreativeSkillConfig) -> list[DirectorQuestion]:
    """Build the three restrained P6 follow-up questions for a selected Skill."""
    emotion_default = _pick_default(skill.default_emotion, EMOTION_OPTIONS, "被鼓舞")
    subject_default = _pick_default(skill.default_subject, SUBJECT_OPTIONS, "普通上班族")
    intensity_default = _normalize_intensity(skill.default_intensity)

    return [
        DirectorQuestion(
            id="audience_emotion",
            title="情绪目标",
            prompt="观众看完后应该产生什么感觉？",
            options=_mark_default(EMOTION_OPTIONS, emotion_default),
            default_value=emotion_default,
        ),
        DirectorQuestion(
            id="subject_profile",
            title="主角/对象",
            prompt="这条视频围绕谁或什么展开？",
            options=_mark_default(SUBJECT_OPTIONS, subject_default),
            default_value=subject_default,
        ),
        DirectorQuestion(
            id="style_intensity",
            title="风格强度",
            prompt="这条视频应该多“风格化”？",
            options=_mark_default(INTENSITY_OPTIONS, intensity_default),
            default_value=intensity_default,
        ),
    ]


def normalize_director_answers(
    raw_answers: Mapping[str, str | None] | None,
    skill: CreativeSkillConfig,
) -> PromptDirectorAnswers:
    """Apply Skill defaults when the user skips a question or answers '默认'."""
    raw_answers = raw_answers or {}
    questions = {q.id: q for q in build_director_questions(skill)}
    custom_notes: list[str] = []

    audience_emotion = _answer_or_default(raw_answers.get("audience_emotion"), questions["audience_emotion"])
    subject_profile = _answer_or_default(raw_answers.get("subject_profile"), questions["subject_profile"])
    style_intensity = _normalize_intensity(
        _answer_or_default(raw_answers.get("style_intensity"), questions["style_intensity"])
    )

    if audience_emotion == "自定义":
        note = _clean(raw_answers.get("audience_emotion_custom"))
        audience_emotion = note or questions["audience_emotion"].default_value
        if note:
            custom_notes.append(f"audience_emotion={note}")

    if subject_profile == "自定义":
        note = _clean(raw_answers.get("subject_profile_custom"))
        subject_profile = note or questions["subject_profile"].default_value
        if note:
            custom_notes.append(f"subject_profile={note}")

    if _clean(raw_answers.get("extra_note")):
        custom_notes.append(_clean(raw_answers.get("extra_note")))

    return PromptDirectorAnswers(
        audience_emotion=audience_emotion,
        subject_profile=subject_profile,
        style_intensity=style_intensity,
        custom_notes=custom_notes,
    )


def build_user_intent(
    raw_idea: str,
    skill: CreativeSkillConfig,
    raw_answers: Mapping[str, str | None] | None = None,
) -> UserIntent:
    """Combine user idea + Skill + normalized answers into a P6.2 intent object."""
    answers = normalize_director_answers(raw_answers, skill)
    return UserIntent(
        raw_idea=str(raw_idea or "").strip(),
        skill_id=skill.id,
        skill_name=skill.name,
        audience_emotion=answers.audience_emotion,
        subject_profile=answers.subject_profile,
        style_intensity=answers.style_intensity,
        custom_notes=answers.custom_notes,
    )


def format_questions_for_feishu(skill: CreativeSkillConfig) -> str:
    """Format the 3 questions as a compact Feishu-friendly message."""
    lines = [f"Prompt Director 追问（Skill：{skill.name}）"]
    for index, question in enumerate(build_director_questions(skill), start=1):
        lines.append(f"\n{index}. {question.title}：{question.prompt}")
        for option in question.options:
            marker = "（默认）" if option.is_default else ""
            lines.append(f"  - {option.label}{marker}")
    lines.append("\n可以回答“默认”跳过，系统会按当前 Skill 自动补齐。")
    return "\n".join(lines)


def _clean(value: str | None) -> str:
    return str(value or "").strip()


def _is_default_marker(value: str | None) -> bool:
    return _clean(value).lower() in DEFAULT_MARKERS


def _pick_default(value: str, options: list[QuestionOption], fallback: str) -> str:
    cleaned = _clean(value)
    allowed = {option.value for option in options}
    return cleaned if cleaned in allowed else fallback


def _normalize_intensity(value: str | None) -> StyleIntensity:
    cleaned = _clean(value)
    if cleaned in STYLE_INTENSITY_VALUES:
        return cleaned  # type: ignore[return-value]
    return "标准增强"


def _answer_or_default(value: str | None, question: DirectorQuestion) -> str:
    if _is_default_marker(value):
        return question.default_value
    cleaned = _clean(value)
    allowed = {option.value for option in question.options}
    return cleaned if cleaned in allowed else question.default_value


def _mark_default(options: list[QuestionOption], default_value: str) -> list[QuestionOption]:
    return [
        option.model_copy(update={"is_default": option.value == default_value})
        for option in options
    ]
