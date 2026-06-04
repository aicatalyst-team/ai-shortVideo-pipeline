"""
Phase 3 — Trending topic analyzer + AI-powered topic recommendation.

Analyzes hot topics, scores them for video potential, and recommends Top 5.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import TrendingTopic
from integrations.llm_client import call_deepseek
from layers.L1_trending.fetcher import get_latest_trending
from layers.L1_trending.recommender import get_feedback_boost

logger = logging.getLogger(__name__)

ANALYZER_SYSTEM_PROMPT = """你是一位短视频选题专家。分析以下热搜词条，从中推荐最适合制作短视频的 5 个选题。

评分维度：
1. 话题热度（当前讨论量）
2. 视觉表现力（是否容易用画面表达）
3. 情绪共鸣（是否能引发观众情绪反应）
4. 创作空间（是否有足够的创意发挥余地）
5. 时效性（热度能持续多久）

输出严格 JSON 格式：
[
  {
    "rank": 1,
    "title": "选题标题",
    "source_platform": "weibo/douyin/bilibili",
    "score": 85,
    "reason": "推荐理由（一句话）",
    "angle": "建议切入角度",
    "style_hint": "适合的视频风格（搞笑/热血/治愈/悬疑/科普等）"
  }
]
"""


async def analyze_and_recommend(
    session: AsyncSession,
    limit: int = 5,
    style_filter: Optional[str] = None,
) -> list[dict]:
    topics = await get_latest_trending(session, limit=30)
    if not topics:
        return []

    topics_text = "\n".join(
        f"[{t.platform}] #{t.rank} {t.title} (热度: {t.hot_score or '未知'})"
        for t in topics
    )

    user_prompt = f"以下是当前各平台热搜：\n\n{topics_text}\n\n请推荐最适合做短视频的 Top {limit} 选题。"
    if style_filter:
        user_prompt += f"\n偏好风格：{style_filter}"

    try:
        response = await call_deepseek(
            system=ANALYZER_SYSTEM_PROMPT,
            user=user_prompt,
            temperature=0.7,
        )
        # 去除 markdown 代码块包裹
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3].strip()
        recommendations = json.loads(text)
        if isinstance(recommendations, list):
            enriched = []
            for item in recommendations[:limit]:
                try:
                    boost = await get_feedback_boost(session, item.get("title", ""))
                except Exception:
                    boost = 0.0
                base_score = float(item.get("score", 0) or 0)
                item["feedback_boost"] = boost
                item["final_score"] = round(base_score + boost, 2)
                enriched.append(item)
            enriched.sort(key=lambda x: x.get("final_score", x.get("score", 0)), reverse=True)
            for idx, item in enumerate(enriched, start=1):
                item["rank"] = idx
            return enriched[:limit]
    except Exception as e:
        logger.error(f"Topic analysis failed: {e}")

    return []


def format_recommendations(recs: list[dict]) -> str:
    if not recs:
        return "暂时无法生成推荐，请确认热搜数据已抓取。"

    lines = ["🧠 AI 选题推荐 Top 5：\n"]
    for r in recs:
        lines.append(
            f"{r['rank']}. 【{r.get('style_hint', '通用')}】{r['title']}\n"
            f"   ⭐ {r.get('final_score', r.get('score', 0))}分 | 来源: {r.get('source_platform', '-')}\n"
            f"   💡 {r['reason']}\n"
            f"   🎬 切入角度: {r['angle']}\n"
        )
    lines.append("\n回复序号开始创作，例如回复「1」即可 👆")
    return "\n".join(lines)
