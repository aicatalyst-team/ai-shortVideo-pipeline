from __future__ import annotations

import logging

from core.parsers import parse_json_array
from integrations.llm_client import call_deepseek

log = logging.getLogger(__name__)

VARIANT_SYSTEM_PROMPT = """你是短视频爆款裂变专家。

任务：基于一条已经表现很好的视频，快速裂变出 5 条新变体。

裂变原则：
1. 保留原主题中最有效的信息核
2. 每条至少变化一个维度：Hook / 切入角度 / 垂类表达 / 情绪风格
3. 不能只是改几个字，要让观众觉得是“同主题下的新内容”
4. 适配图文混剪+解说类短视频

输出严格 JSON 数组：
[
  {
    "index": 1,
    "theme": "新主题",
    "angle": "新切入角度",
    "style_name": "hot_news_commentary",
    "hook_hint": "前3秒钩子",
    "reason": "为什么这个变体值得做"
  }
]
只输出 JSON，不要其他文字。
"""


async def generate_variants(
    seed_title: str,
    seed_theme: str,
    style_name: str,
    narration: str,
    structure_hints: list[dict] | None = None,
    count: int = 5,
) -> list[dict]:
    structure_text = ""
    if structure_hints:
        top = structure_hints[:5]
        structure_text = "\n可参考的高表现结构：\n" + "\n".join(
            f"- {item.get('structure')} | {item.get('title') or item.get('theme')}"
            for item in top
        )

    user_prompt = (
        f"原视频标题：{seed_title}\n"
        f"原视频主题：{seed_theme}\n"
        f"原风格：{style_name}\n"
        f"原旁白：{narration[:800]}\n"
        f"{structure_text}\n\n"
        f"请裂变出 {count} 条新变体。"
    )
    raw = await call_deepseek(VARIANT_SYSTEM_PROMPT, user_prompt, temperature=0.9)
    variants = parse_json_array(raw)
    return variants[:count]


def format_variants(variants: list[dict]) -> str:
    if not variants:
        return "未生成可用变体。"
    lines = ["爆款裂变建议：\n"]
    for item in variants:
        lines.append(
            f"{item.get('index', '?')}. {item.get('theme', '')}\n"
            f"   角度：{item.get('angle', '')}\n"
            f"   Hook：{item.get('hook_hint', '')}\n"
            f"   理由：{item.get('reason', '')}\n"
        )
    return "\n".join(lines)
