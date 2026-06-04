from __future__ import annotations

from layers.L2_creative.creative_skills import get_creative_skill
from layers.L2_creative.prompt_director import (
    build_director_questions,
    build_user_intent,
    format_questions_for_feishu,
    normalize_director_answers,
    summarize_user_intent,
)
from layers.L2_creative.prompt_director.schemas import UserIntent


def _skill(name: str):
    skill = get_creative_skill(name)
    assert skill is not None
    return skill


def test_build_director_questions_returns_three_questions():
    questions = build_director_questions(_skill("电影"))

    assert [q.id for q in questions] == [
        "audience_emotion",
        "subject_profile",
        "style_intensity",
    ]


def test_question_defaults_come_from_skill_yaml():
    questions = {q.id: q for q in build_director_questions(_skill("朋友圈"))}

    assert questions["audience_emotion"].default_value == "被治愈"
    assert questions["subject_profile"].default_value == "普通上班族"
    assert questions["style_intensity"].default_value == "克制真实"


def test_default_options_are_marked():
    questions = {q.id: q for q in build_director_questions(_skill("抖音"))}

    defaults = [
        option.value
        for option in questions["style_intensity"].options
        if option.is_default
    ]
    assert defaults == ["强风格化"]


def test_normalize_answers_uses_skill_defaults_when_missing():
    answers = normalize_director_answers({}, _skill("产品"))

    assert answers.audience_emotion == "想购买/咨询"
    assert answers.subject_profile == "产品/品牌"
    assert answers.style_intensity == "标准增强"


def test_normalize_answers_uses_skill_defaults_for_default_marker():
    answers = normalize_director_answers(
        {
            "audience_emotion": "默认",
            "subject_profile": "不填",
            "style_intensity": "都行",
        },
        _skill("电影"),
    )

    assert answers.audience_emotion == "被鼓舞"
    assert answers.subject_profile == "普通上班族"
    assert answers.style_intensity == "标准增强"


def test_normalize_answers_accepts_valid_user_choices():
    answers = normalize_director_answers(
        {
            "audience_emotion": "被震撼",
            "subject_profile": "创业者/技术人",
            "style_intensity": "强风格化",
        },
        _skill("知识"),
    )

    assert answers.audience_emotion == "被震撼"
    assert answers.subject_profile == "创业者/技术人"
    assert answers.style_intensity == "强风格化"


def test_unknown_answer_falls_back_to_skill_default():
    answers = normalize_director_answers(
        {
            "audience_emotion": "赛博柠檬味",
            "subject_profile": "银河猫",
            "style_intensity": "过曝到火星",
        },
        _skill("朋友圈"),
    )

    assert answers.audience_emotion == "被治愈"
    assert answers.subject_profile == "普通上班族"
    assert answers.style_intensity == "克制真实"


def test_custom_answers_are_preserved_as_notes():
    answers = normalize_director_answers(
        {
            "audience_emotion": "自定义",
            "audience_emotion_custom": "看完想立刻行动",
            "subject_profile": "自定义",
            "subject_profile_custom": "30 岁独立开发者",
            "extra_note": "不要太广告",
        },
        _skill("产品"),
    )

    assert answers.audience_emotion == "看完想立刻行动"
    assert answers.subject_profile == "30 岁独立开发者"
    assert "audience_emotion=看完想立刻行动" in answers.custom_notes
    assert "subject_profile=30 岁独立开发者" in answers.custom_notes
    assert "不要太广告" in answers.custom_notes


def test_build_user_intent_returns_pydantic_model():
    intent = build_user_intent(
        "做一条 AI 编程效率短片",
        _skill("电影"),
        {"audience_emotion": "被震撼"},
    )

    assert isinstance(intent, UserIntent)
    assert intent.raw_idea == "做一条 AI 编程效率短片"
    assert intent.skill_id == "cinematic_narrative"
    assert intent.audience_emotion == "被震撼"


def test_format_questions_for_feishu_contains_three_questions_and_default_tip():
    msg = format_questions_for_feishu(_skill("抖音"))

    assert "Prompt Director 追问" in msg
    assert "1. 情绪目标" in msg
    assert "2. 主角/对象" in msg
    assert "3. 风格强度" in msg
    assert "默认" in msg


def test_summarize_user_intent_is_human_readable():
    intent = build_user_intent("讲清楚大模型 Agent", _skill("知识"), {})
    summary = summarize_user_intent(intent)

    assert "用户想法：讲清楚大模型 Agent" in summary
    assert "Skill：知识科普短片" in summary
    assert "风格强度：标准增强" in summary
