"""Hook 多变体生成器

为每条解说稿生成 3 个不同类型的前 3 秒 Hook 变体，
提升算法推流概率（高完播率的核心是前 3 秒留住人）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from config.settings import get_settings
from integrations.llm_client import get_deepseek

log = logging.getLogger(__name__)

# ── Hook 类型定义 ──

HOOK_TYPES = {
    "suspense": "悬念型",
    "reversal": "反转型",
    "data": "数据冲击型",
    "empathy": "共情型",
    "conflict": "冲突对立型",
}

# 垂类 → 优先 Hook 类型
VERTICAL_HOOK_PRIORITY: dict[str, list[str]] = {
    "hot_news_commentary": ["data", "conflict", "suspense"],
    "knowledge_explainer": ["data", "suspense", "reversal"],
    "emotional_story":     ["empathy", "reversal", "suspense"],
    "curiosity_facts":     ["suspense", "data", "reversal"],
    "social_insight":      ["conflict", "empathy", "reversal"],
}

# Hook 写作模板（给 LLM 的示例参考）
HOOK_EXAMPLES: dict[str, str] = {
    "suspense": (
        "用未知/神秘开场，让观众必须看下去才能得到答案。\n"
        "示例：「你知道为什么有人年薪百万却活得不如月薪三千的人快乐吗？」\n"
        "示例：「这个视频发出去可能被删，但我还是要说」"
    ),
    "reversal": (
        "先给出一个常识性判断，再立刻用事实打脸，制造认知冲突。\n"
        "示例：「大家都以为勤劳能致富——但数据告诉你完全相反的答案」\n"
        "示例：「我原本也觉得他说得对，直到我看到了这组数字」"
    ),
    "data": (
        "用震撼数字直接砸脸，让观众第一秒就感到冲击。\n"
        "示例：「中国 14 亿人，只有不到 3% 的人知道这件事」\n"
        "示例：「这一个决策，让他 30 天损失了 2000 万」"
    ),
    "empathy": (
        "说出观众心里最想说但没说出口的话，瞬间共鸣。\n"
        "示例：「你有没有那种感觉——努力了很多年，却觉得哪里不对」\n"
        "示例：「我妈跟我说的那句话，我想了三年才明白」"
    ),
    "conflict": (
        "制造明确的对立或争议，让观众想站队、想评论。\n"
        "示例：「月薪一万的人瞧不起送外卖的，我觉得这件事很可笑」\n"
        "示例：「专家说年轻人应该奋斗，但没人告诉你奋斗的代价」"
    ),
}


@dataclass
class HookVariant:
    hook_type: str
    hook_type_name: str
    hook_text: str
    reason: str


@dataclass
class HookResult:
    variants: list[HookVariant]
    recommended: str  # 推荐的 hook_type


async def generate_hook_variants(
    narration: str,
    style_name: str,
    n: int = 3,
) -> HookResult:
    """为解说稿生成 n 个 Hook 变体，按垂类优先顺序排列。"""
    log.info("[Hook引擎] style=%s narration前50字=%s", style_name, narration[:50])

    priority = VERTICAL_HOOK_PRIORITY.get(style_name, ["suspense", "data", "conflict"])
    selected_types = priority[:n]

    examples_text = "\n\n".join(
        f"【{HOOK_TYPES[t]}（{t}）】\n{HOOK_EXAMPLES[t]}"
        for t in selected_types
    )

    system_prompt = (
        "你是短视频 Hook 文案专家，擅长写抖音前 3 秒留人文案。\n\n"
        f"以下是 {n} 种 Hook 类型的写法示例：\n\n{examples_text}\n\n"
        "任务：针对给定的解说稿内容，分别写出这 3 种类型的 Hook 文案。\n\n"
        "要求：\n"
        "1. 每个 Hook 必须在 3 秒内读完（约 20-30 字）\n"
        "2. Hook 要和解说稿内容强相关，不是通用模板\n"
        "3. 语言口语化，像真人说话\n\n"
        f"输出 JSON 数组，{n} 条，每条含：\n"
        "- hook_type: 类型代号（suspense/reversal/data/empathy/conflict）\n"
        "- hook_text: Hook 文案\n"
        "- reason: 为什么这个 Hook 适合这条内容（一句话）\n\n"
        "只输出 JSON，不要其他文字。"
    )

    type_list = "、".join(HOOK_TYPES[t] for t in selected_types)
    user_msg = (
        f"请为以下解说稿生成「{type_list}」3 种 Hook：\n\n{narration[:600]}"
    )

    resp = await get_deepseek().chat.completions.create(
        model=get_settings().deepseek_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=800,
    )

    raw = resp.choices[0].message.content.strip()
    log.info("[Hook引擎] 返回 %d 字", len(raw))

    from core.parsers import parse_json_array
    items = parse_json_array(raw)

    variants = []
    for item in items:
        t = item.get("hook_type", selected_types[len(variants)] if len(variants) < len(selected_types) else "suspense")
        variants.append(HookVariant(
            hook_type=t,
            hook_type_name=HOOK_TYPES.get(t, t),
            hook_text=item.get("hook_text", ""),
            reason=item.get("reason", ""),
        ))

    recommended = selected_types[0] if selected_types else "suspense"
    return HookResult(variants=variants, recommended=recommended)


def format_hook_variants(result: HookResult) -> str:
    lines = ["🎯 Hook 变体（前3秒文案）：\n"]
    for i, v in enumerate(result.variants, 1):
        marker = "⭐ 推荐" if v.hook_type == result.recommended else f"  变体{i}"
        lines.append(f"{marker}【{v.hook_type_name}】")
        lines.append(f"  {v.hook_text}")
        lines.append(f"  → {v.reason}\n")
    lines.append("发「确认」时系统自动使用推荐 Hook。")
    return "\n".join(lines)
