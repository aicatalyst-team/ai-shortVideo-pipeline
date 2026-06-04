"""
Phase 3 — Topic recommender with historical performance weighting.

Uses past publish data to refine topic scoring over time.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Plan, TrendingTopic, VideoMetric, VideoRecord

logger = logging.getLogger(__name__)


async def get_successful_themes(session: AsyncSession, days: int = 30) -> list[str]:
    """Get themes from plans that were successfully published recently."""
    cutoff = datetime.now() - timedelta(days=days)
    stmt = (
        select(Plan.theme)
        .where(Plan.status == "published", Plan.created_at >= cutoff)
        .order_by(Plan.created_at.desc())
        .limit(50)
    )
    result = await session.execute(stmt)
    return [r[0] for r in result.all() if r[0]]


async def get_topic_frequency(session: AsyncSession, title: str) -> int:
    """Check how many times a similar topic has appeared in trending."""
    stmt = select(func.count()).select_from(TrendingTopic).where(
        TrendingTopic.title.ilike(f"%{title}%")
    )
    result = await session.execute(stmt)
    return result.scalar() or 0


async def should_auto_generate(session: AsyncSession, topic: TrendingTopic) -> bool:
    """Determine if a topic is hot enough to trigger auto-generation."""
    if not topic.hot_score:
        return False
    # Auto-trigger if: score > 1M AND topic appeared in trending 3+ times
    frequency = await get_topic_frequency(session, topic.title)
    return topic.hot_score > 1_000_000 and frequency >= 3


async def get_feedback_boost(session: AsyncSession, title: str) -> float:
    """Compute a recommendation boost based on high-performing historical videos."""
    stmt = (
        select(VideoRecord, VideoMetric)
        .join(VideoMetric, VideoMetric.video_id == VideoRecord.id)
        .order_by(desc(VideoMetric.views), desc(VideoMetric.engagement_rate), desc(VideoMetric.completion_rate))
        .limit(50)
    )
    result = await session.execute(stmt)
    rows = result.all()
    boost = 0.0
    title_tokens = {tok for tok in title.replace("（", " ").replace("）", " ").replace("，", " ").split() if tok}

    for video, metric in rows:
        hay = f"{video.theme} {video.title}"
        matched = any(tok and tok in hay for tok in title_tokens) or any(part in title for part in hay.split()[:3] if part)
        if not matched:
            continue
        metric_score = (
            min((metric.views or 0) / 10000, 8)
            + (metric.completion_rate or 0) * 10
            + (metric.engagement_rate or 0) * 20
        )
        boost += min(metric_score, 15)

    return round(boost, 2)
