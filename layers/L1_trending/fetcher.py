"""
Phase 3 — Hot topic fetcher for Douyin, Weibo, Bilibili.

Uses public APIs / web scraping to pull trending topics.
Results are persisted to PostgreSQL (trending_topics table).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import TrendingTopic

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}


async def fetch_all(session: AsyncSession, platforms: list[str] | None = None) -> dict[str, list[dict]]:
    from config.settings import get_settings
    platforms = platforms or get_settings().trending_platforms
    results = {}
    for platform in platforms:
        fetcher = _FETCHERS.get(platform)
        if fetcher:
            try:
                items = await fetcher()
                await _save_to_db(session, platform, items)
                results[platform] = items
                logger.info(f"Fetched {len(items)} trending topics from {platform}")
            except Exception as e:
                logger.error(f"Failed to fetch trending from {platform}: {e}")
                results[platform] = []
    return results


async def _save_to_db(session: AsyncSession, platform: str, items: list[dict]) -> None:
    for item in items:
        topic = TrendingTopic(
            platform=platform,
            rank=item.get("rank", 0),
            title=item["title"],
            url=item.get("url", ""),
            hot_score=item.get("hot_score"),
            extra=item.get("extra"),
        )
        session.add(topic)
    await session.flush()


# ── Platform-specific fetchers ────────────────────────────────────────────────

async def _fetch_weibo() -> list[dict]:
    """Fetch Weibo hot search via public API."""
    url = "https://weibo.com/ajax/side/hotSearch"
    async with httpx.AsyncClient(headers=HEADERS, timeout=15) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

    items = []
    for i, entry in enumerate(data.get("data", {}).get("realtime", [])[:30]):
        items.append({
            "rank": i + 1,
            "title": entry.get("word", ""),
            "hot_score": float(entry.get("num", 0)),
            "url": f"https://s.weibo.com/weibo?q=%23{entry.get('word', '')}%23",
            "extra": {"category": entry.get("category", ""), "icon_desc": entry.get("icon_desc", "")},
        })
    return items


async def _fetch_douyin() -> list[dict]:
    """Fetch Douyin hot search via public endpoint."""
    url = "https://www.douyin.com/aweme/v1/web/hot/search/list/"
    async with httpx.AsyncClient(headers=HEADERS, timeout=15) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

    items = []
    word_list = data.get("data", {}).get("word_list", [])
    for i, entry in enumerate(word_list[:30]):
        items.append({
            "rank": i + 1,
            "title": entry.get("word", ""),
            "hot_score": float(entry.get("hot_value", 0)),
            "url": f"https://www.douyin.com/search/{entry.get('word', '')}",
            "extra": {"event_time": entry.get("event_time", "")},
        })
    return items


async def _fetch_bilibili() -> list[dict]:
    """Fetch Bilibili hot search via public API."""
    url = "https://api.bilibili.com/x/web-interface/wbi/search/square?limit=30"
    async with httpx.AsyncClient(headers=HEADERS, timeout=15) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

    items = []
    trending = data.get("data", {}).get("trending", {}).get("list", [])
    for i, entry in enumerate(trending[:30]):
        items.append({
            "rank": i + 1,
            "title": entry.get("keyword", ""),
            "hot_score": float(entry.get("heat_score", 0)) if entry.get("heat_score") else None,
            "url": f"https://search.bilibili.com/all?keyword={entry.get('keyword', '')}",
            "extra": {"icon": entry.get("icon", "")},
        })
    return items


_FETCHERS = {
    "weibo": _fetch_weibo,
    "douyin": _fetch_douyin,
    "bilibili": _fetch_bilibili,
}


# ── Query helpers ─────────────────────────────────────────────────────────────

async def get_latest_trending(session: AsyncSession, platform: Optional[str] = None, limit: int = 10) -> list[TrendingTopic]:
    from sqlalchemy import select
    stmt = select(TrendingTopic).order_by(TrendingTopic.fetched_at.desc(), TrendingTopic.rank.asc())
    if platform:
        stmt = stmt.where(TrendingTopic.platform == platform)
    stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def format_trending_for_feishu(session: AsyncSession, limit: int = 15) -> tuple[str, list[dict]]:
    """Returns (formatted message, topic list for session storage)."""
    topics = await get_latest_trending(session, limit=limit)
    if not topics:
        return "暂无热搜数据，请稍后再试。", []

    lines = ["最新热搜 Top：\n"]
    topic_list = []
    for i, t in enumerate(topics, 1):
        score = f" (热度:{int(t.hot_score)})" if t.hot_score else ""
        lines.append(f"  {i}. [{t.platform}] {t.title}{score}")
        topic_list.append({"index": i, "title": t.title, "platform": t.platform})
    lines.append(f"\n\n回复 1-{len(topics)} 的序号，我来生成视频脚本")
    return "\n".join(lines), topic_list
