"""首评话术库生成器

为每条视频生成 3 条「钩子评论」，发布后手动粘贴到首评位置，
引导算法推流和观众互动。

策略：
- 钩子评论 = 引导评论的问题 / 争议点 / 情感共鸣句
- 不是广告文案，像真实观众自发评论
- 按垂类定制话术风格
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from config.settings import get_settings
from core.parsers import parse_json_array
from integrations.llm_client import get_deepseek

log = logging.getLogger(__name__)

# 垂类首评策略
VERTICAL_COMMENT_STRATEGY: dict[str, str] = {
    "hot_news_commentary": (
        "引导观众站队或表达观点。用疑问或争议触发评论。\n"
        "例如：「你们觉得这件事谁的责任更大？」\n"
        "例如：「这种事身边有人遇到过吗，说说你的经历」"
    ),
    "knowledge_explainer": (
        "引导观众分享相关知识或经历，或追问更多内容。\n"
        "例如：「还有一个更震撼的冷知识，你们想不想知道？」\n"
        "例如：「我第一次知道这个的时候也惊呆了，你们呢？」"
    ),
    "emotional_story": (
        "触发情感共鸣，引导观众分享相似经历。\n"
        "例如：「有没有人看完眼睛湿了，不只是我吧」\n"
        "例如：「评论区说说你最难忘的一句妈妈说过的话」"
    ),
    "curiosity_facts": (
        "用悬念追问，引导观众追更多内容。\n"
        "例如：「下一个更离谱，你们猜猜是什么」\n"
        "例如：「这个是真的假的？查了一下居然是真的！」"
    ),
    "social_insight": (
        "挑起讨论和站队，争议性强。\n"
        "例如：「同意的扣1，不同意的扣2，看看比例」\n"
        "例如：「说出了多少人的心声，但没人敢明说」"
    ),
}


@dataclass
class CommentVariant:
    text: str
    strategy: str   # hook / empathy / question / controversy
    expected_reply_rate: str  # high / medium


@dataclass
class CommentPlan:
    first_comments: list[CommentVariant]
    pinned_suggestion: str   # 建议置顶的那条
    posting_tip: str         # 发布小技巧


async def generate_comments(
    narration: str,
    style_name: str,
    title: str = "",
) -> CommentPlan:
    """为视频生成 3 条首评话术。"""
    log.info("[首评引擎] style=%s", style_name)

    strategy = VERTICAL_COMMENT_STRATEGY.get(style_name, VERTICAL_COMMENT_STRATEGY["hot_news_commentary"])

    system_prompt = (
        "你是短视频运营专家，擅长写能引爆评论区的首评话术。\n\n"
        f"本视频垂类首评策略：\n{strategy}\n\n"
        "任务：为这条视频写 3 条首评，分别对应不同的引流策略。\n\n"
        "要求：\n"
        "1. 像真实观众写的，不像官方营销文案\n"
        "2. 字数控制在 20-50 字\n"
        "3. 至少 1 条带疑问句，引导回复\n"
        "4. 不要用「本视频」「博主」这类词\n\n"
        "输出 JSON 数组，3 条，每条含：\n"
        "- text: 评论文案\n"
        "- strategy: 策略类型（hook/empathy/question/controversy）\n"
        "- expected_reply_rate: 预期回复率（high/medium）\n\n"
        "只输出 JSON，不要其他文字。"
    )

    context = f"标题：{title}\n\n解说稿摘要：\n{narration[:400]}" if title else f"解说稿摘要：\n{narration[:400]}"

    resp = await get_deepseek().chat.completions.create(
        model=get_settings().deepseek_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
        ],
        max_tokens=500,
    )

    raw = resp.choices[0].message.content.strip()
    items = parse_json_array(raw)

    comments = []
    for item in items:
        comments.append(CommentVariant(
            text=item.get("text", ""),
            strategy=item.get("strategy", "hook"),
            expected_reply_rate=item.get("expected_reply_rate", "medium"),
        ))

    # 推荐置顶预期回复率最高的那条
    pinned = next((c.text for c in comments if c.expected_reply_rate == "high"), comments[0].text if comments else "")

    posting_tip = _get_posting_tip(style_name)

    log.info("[首评引擎] 生成 %d 条首评", len(comments))
    return CommentPlan(
        first_comments=comments,
        pinned_suggestion=pinned,
        posting_tip=posting_tip,
    )


def _get_posting_tip(style_name: str) -> str:
    tips = {
        "hot_news_commentary": "发布后 30 分钟内手动回复前 5 条评论，加速冷启动",
        "knowledge_explainer": "在首评区预告「下期更震撼」，引导关注",
        "emotional_story":     "发布后先不要删低赞评论，情感类视频需要真实讨论氛围",
        "curiosity_facts":     "首评用「更多离谱内容在下期」制造期待感",
        "social_insight":      "争议类内容发布后 1 小时内持续刷评论区并回复，引爆讨论",
    }
    return tips.get(style_name, "发布后 1 小时内积极互动，加速算法推流")


def format_comment_plan(plan: CommentPlan) -> str:
    lines = ["💬 首评话术（发布后立即粘贴到评论区）：\n"]
    for i, c in enumerate(plan.first_comments, 1):
        rate_icon = "🔥" if c.expected_reply_rate == "high" else "💡"
        lines.append(f"{rate_icon} 首评{i}【{c.strategy}】：")
        lines.append(f"  {c.text}\n")

    lines.append(f"⭐ 建议置顶：{plan.pinned_suggestion}\n")
    lines.append(f"📌 运营小贴士：{plan.posting_tip}")
    return "\n".join(lines)
