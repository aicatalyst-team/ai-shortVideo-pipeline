from __future__ import annotations

from layers.L2_creative.creative_skills import get_creative_skill
from layers.L2_creative.prompt_director import (
    DEFAULT_NEGATIVE_CONSTRAINTS,
    SKILL_PROMPT_PRESETS,
    build_narrative_plan,
    build_shot_plan,
    build_user_intent,
    compile_clip_prompts,
    compile_model_prompt,
    compile_prompt_director_plan,
    summarize_user_intent,
)
from layers.L2_creative.prompt_director.schemas import (
    ModelPrompt,
    NarrativePlan,
    PromptDirectorPlan,
    ShotPlan,
)


def _intent(skill_alias: str = "电影"):
    skill = get_creative_skill(skill_alias)
    assert skill is not None
    return build_user_intent(
        "做一条 AI 编程效率短片",
        skill,
        {
            "audience_emotion": "被震撼",
            "subject_profile": "创业者/技术人",
            "style_intensity": "标准增强",
        },
    )


def test_build_narrative_plan_returns_required_four_fields():
    plan = build_narrative_plan(_intent())

    assert isinstance(plan, NarrativePlan)
    assert "前 3 秒" in plan.hook
    assert plan.emotional_arc
    assert "一个清晰冲突" in plan.conflict_or_turning_point
    assert "画面记忆点" in plan.ending_memory_point


def test_build_shot_plan_uses_skill_preset():
    shot = build_shot_plan(_intent("电影"), clip_index=1, narration_segment="AI 正在改变写代码方式")

    assert isinstance(shot, ShotPlan)
    assert shot.shot_type == "medium_shot"
    assert "rule of thirds" in shot.composition
    assert "AI 正在改变写代码方式" in shot.subject_action


def test_style_intensity_changes_motion_for_restrained_realism():
    skill = get_creative_skill("朋友圈")
    assert skill is not None
    intent = build_user_intent("真实记录一个程序员的一天", skill, {"style_intensity": "克制真实"})
    shot = build_shot_plan(intent, clip_index=1, narration_segment="他安静地打开电脑")

    assert shot.camera_motion == "mostly static, subtle natural movement"
    assert "restrained realism" in shot.lighting


def test_compile_model_prompt_contains_hard_rules():
    intent = _intent()
    narrative = build_narrative_plan(intent)
    shot = build_shot_plan(intent, clip_index=1, narration_segment="他把重复工作交给 Agent")
    prompt = compile_model_prompt(intent, narrative, shot)

    assert isinstance(prompt, ModelPrompt)
    assert "single main action" in prompt.visual_prompt
    assert "one main action only" in prompt.kling_prompt
    assert "avoid complex multi-step motion" in prompt.kling_prompt


def test_compile_model_prompt_includes_default_negative_constraints():
    prompt = compile_prompt_director_plan(_intent()).model_prompt

    for item in DEFAULT_NEGATIVE_CONSTRAINTS:
        assert item in prompt.negative_prompt


def test_compile_model_prompt_respects_prompt_budget():
    long_idea = "AI 编程效率" * 500
    skill = get_creative_skill("知识")
    assert skill is not None
    intent = build_user_intent(long_idea, skill, {})

    prompt = compile_prompt_director_plan(intent, prompt_budget=180).model_prompt

    assert len(prompt.visual_prompt) <= 180
    assert prompt.prompt_budget == 180


def test_compile_prompt_director_plan_returns_four_layer_model():
    plan = compile_prompt_director_plan(
        _intent("抖音"),
        clip_index=2,
        narration_segment="三秒内先抛出最大反差",
    )

    assert isinstance(plan, PromptDirectorPlan)
    assert plan.user_intent.skill_id == "douyin_viral"
    assert plan.shot_plan.clip_index == 2
    assert plan.model_prompt.visual_prompt


def test_compile_clip_prompts_returns_one_plan_per_non_empty_segment():
    plans = compile_clip_prompts(_intent(), ["第一段", "", "第三段"])

    assert [p.shot_plan.clip_index for p in plans] == [1, 3]
    assert [p.shot_plan.narration_segment for p in plans] == ["第一段", "第三段"]


def test_all_five_skill_presets_are_covered():
    assert {
        "cinematic_narrative",
        "douyin_viral",
        "wechat_real",
        "product_ad",
        "knowledge",
    }.issubset(SKILL_PROMPT_PRESETS)


def test_five_skills_compile_to_distinct_prompt_tones():
    tones = []
    for alias in ["电影", "抖音", "朋友圈", "产品", "知识"]:
        plan = compile_prompt_director_plan(_intent(alias))
        tones.append(plan.model_prompt.visual_prompt.split(",", 1)[0])

    assert len(set(tones)) == 5


def test_unknown_skill_falls_back_to_douyin_preset():
    intent = _intent()
    intent.skill_id = "unknown_skill"
    plan = compile_prompt_director_plan(intent)

    assert "viral hook" in plan.model_prompt.visual_prompt


def test_summarize_user_intent_still_works_after_compiler_upgrade():
    summary = summarize_user_intent(_intent("知识"))

    assert "用户想法：做一条 AI 编程效率短片" in summary
    assert "Skill：知识科普短片" in summary
