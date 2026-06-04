from __future__ import annotations

import logging
from collections import Counter

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import VideoMetric, VideoRecord

log = logging.getLogger(__name__)


def _derive_structure_label(narration: str, title: str) -> str:
    text = f"{title} {narration}"
    if any(k in text for k in ["为什么", "真相", "你知道吗", "想不到"]):
        return "hook-question-explain"
    if any(k in text for k in ["第一", "第二", "第三", "3个", "5个"]):
        return "listicle-breakdown"
    if any(k in text for k in ["故事", "后来", "直到", "那天"]):
        return "story-reveal"
    if any(k in text for k in ["结论", "所以", "本质", "核心"]):
        return "claim-proof-conclusion"
    return "hook-fact-comment"


async def build_structure_library(session: AsyncSession, limit: int = 20) -> list[dict]:
    """Build a lightweight reusable structure library from high-performing videos."""
    stmt = (
        select(VideoRecord, VideoMetric)
        .join(VideoMetric, VideoMetric.video_id == VideoRecord.id)
        .order_by(desc(VideoMetric.views), desc(VideoMetric.engagement_rate), desc(VideoMetric.completion_rate))
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.all()
    library: list[dict] = []
    for video, metric in rows:
        structure = _derive_structure_label(video.narration or "", video.title or video.theme or "")
        library.append(
            {
                "video_id": video.id,
                "style_name": video.style_name,
                "theme": video.theme,
                "title": video.title,
                "structure": structure,
                "views": metric.views,
                "completion_rate": metric.completion_rate,
                "engagement_rate": metric.engagement_rate,
            }
        )
    return library


def summarize_structure_library(items: list[dict]) -> str:
    if not items:
        return "暂无可复用的爆款结构。"
    counts = Counter(item["structure"] for item in items if item.get("structure"))
    lines = ["高表现结构统计："]
    for name, count in counts.most_common(5):
        lines.append(f"- {name}: {count}")
    return "\n".join(lines)
