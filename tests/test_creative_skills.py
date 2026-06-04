from __future__ import annotations

from layers.L2_creative.creative_skills import (
    format_creative_skills_for_feishu,
    get_creative_skill,
    list_creative_skills,
    load_creative_skills,
)


def test_loads_builtin_creative_skills():
    skills = load_creative_skills(force=True)

    assert {
        "cinematic_narrative",
        "douyin_viral",
        "wechat_real",
        "product_ad",
        "knowledge",
    }.issubset(skills)


def test_resolves_chinese_alias_for_cinematic_skill():
    skill = get_creative_skill("电影")

    assert skill is not None
    assert skill.id == "cinematic_narrative"
    assert skill.default_prompt_style == "emotional_story"


def test_resolves_chinese_alias_for_douyin_skill():
    skill = get_creative_skill("抖音")

    assert skill is not None
    assert skill.id == "douyin_viral"
    assert skill.default_prompt_style == "hot_news_commentary"


def test_resolves_id_case_insensitively():
    skill = get_creative_skill("PRODUCT_AD")

    assert skill is not None
    assert skill.name == "产品广告片"


def test_missing_skill_returns_none():
    assert get_creative_skill("不存在的技能") is None


def test_list_creative_skills_is_stable():
    skills = list_creative_skills()

    assert [s.id for s in skills] == sorted(s.id for s in skills)


def test_format_marks_active_skill():
    msg = format_creative_skills_for_feishu("douyin_viral")

    assert "> 抖音爆款短视频（douyin_viral）" in msg
    assert "Skill 抖音" in msg


class _FakeBackgroundTasks:
    def __init__(self) -> None:
        self.tasks = []

    def add_task(self, func, *args, **kwargs):
        self.tasks.append((func, args, kwargs))


async def _noop_send_text(*args, **kwargs):
    return None


def test_webhook_help_mentions_skill_commands():
    from api.webhooks import HELP_TEXT

    assert "Skill" in HELP_TEXT
    assert "Skill 电影" in HELP_TEXT


def test_webhook_skill_command_switches_session(monkeypatch):
    import asyncio
    import api.webhooks as webhooks

    monkeypatch.setattr(webhooks, "send_text", _noop_send_text)
    monkeypatch.setattr(webhooks, "_current_style", "hot_news_commentary")
    monkeypatch.setattr(webhooks, "_current_skill", "")
    webhooks._session_store.pop("chat-p5", None)
    bg = _FakeBackgroundTasks()

    handled = asyncio.run(webhooks._handle_light_command("chat-p5", "Skill 电影", bg))

    session = webhooks._get_session("chat-p5")
    assert handled is True
    assert session["current_skill"] == "cinematic_narrative"
    assert session["style_name"] == "emotional_story"
    assert bg.tasks


def test_dispatch_chain_keeps_active_skill_for_vertical_command(monkeypatch):
    import asyncio
    import api.webhooks as webhooks

    calls = []

    async def fake_run_vertical(cid, theme, style, vertical_key):
        calls.append((cid, theme, style.name, vertical_key))

    monkeypatch.setattr(webhooks, "_run_vertical", fake_run_vertical)
    monkeypatch.setattr(webhooks, "_current_style", "hot_news_commentary")
    monkeypatch.setattr(webhooks, "_current_skill", "")
    webhooks._session_store["chat-p5-dispatch"] = {
        "current_skill": "cinematic_narrative",
        "style_name": "emotional_story",
    }

    asyncio.run(webhooks._dispatch_chain("chat-p5-dispatch", "解说 谷歌大会"))

    assert calls == [("chat-p5-dispatch", "谷歌大会", "emotional_story", "emotional_story")]
