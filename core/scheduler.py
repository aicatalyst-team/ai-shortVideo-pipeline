"""
Phase 3 — Redis connection + ARQ task queue for async job processing.

Handles: video generation, trending fetches, publishing, periodic tasks.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import redis.asyncio as aioredis
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.cron import cron

from config.settings import get_settings
from core.logging_setup import setup_logging

setup_logging("worker")
logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None
_arq_pool: ArqRedis | None = None


# ── Redis connection ──────────────────────────────────────────────────────────

async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        settings = get_settings()
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis():
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


# ── Session store (replaces in-memory _session_store) ─────────────────────────

SESSION_TTL = 12 * 3600  # 12 hours
RUNTIME_TTL = 30 * 24 * 3600  # 30 days


async def session_set(chat_id: str, key: str, value: str) -> None:
    r = await get_redis()
    redis_key = f"session:{chat_id}:{key}"
    await r.set(redis_key, value, ex=SESSION_TTL)


async def session_get(chat_id: str, key: str) -> str | None:
    r = await get_redis()
    return await r.get(f"session:{chat_id}:{key}")


async def session_delete(chat_id: str) -> None:
    r = await get_redis()
    keys = []
    async for key in r.scan_iter(f"session:{chat_id}:*"):
        keys.append(key)
    if keys:
        await r.delete(*keys)


async def runtime_set(key: str, value: str, ttl: int = RUNTIME_TTL) -> None:
    r = await get_redis()
    await r.set(f"runtime:{key}", value, ex=ttl)


async def runtime_get(key: str) -> str | None:
    r = await get_redis()
    return await r.get(f"runtime:{key}")


# ── ARQ task queue ────────────────────────────────────────────────────────────

def _get_redis_settings() -> RedisSettings:
    settings = get_settings()
    url = settings.redis_url
    # Parse redis://host:port/db
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or "0"),
        password=parsed.password,
    )


async def get_arq_pool() -> ArqRedis:
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(_get_redis_settings())
    return _arq_pool


async def enqueue_job(func_name: str, *args: Any, _defer_by: timedelta | None = None, **kwargs: Any) -> str:
    pool = await get_arq_pool()
    job = await pool.enqueue_job(func_name, *args, _defer_by=_defer_by, **kwargs)
    logger.info(f"Enqueued job: {func_name} -> {job.job_id}")
    return job.job_id


async def _upsert_job_status(
    job_id: str,
    *,
    job_type: str,
    status: str,
    result: dict | None = None,
    error: str | None = None,
    started: bool = False,
    finished: bool = False,
    progress: int | None = None,
    progress_stage: str | None = None,
) -> None:
    from db.connection import get_session_factory
    from db.models import Job

    async with get_session_factory()() as session:
        job = await session.get(Job, job_id)
        now = datetime.now()
        if not job:
            job = Job(id=job_id, job_type=job_type, status=status)
            session.add(job)
        else:
            job.job_type = job_type
            job.status = status
        if result is not None:
            job.result = result
        if error is not None:
            job.error = error
        if started and not job.started_at:
            job.started_at = now
        if finished:
            job.finished_at = now
        if progress is not None:
            job.progress = max(0, min(100, int(progress)))
        if progress_stage is not None:
            job.progress_stage = progress_stage[:64]
        await session.commit()


# ── ARQ Worker functions (registered in worker.py) ────────────────────────────

async def task_generate_video(
    ctx: dict,
    chat_id: str,
    theme: str,
    style_name: str = "hot_news_commentary",
    source: str = "batch",
    choice_idx: int = 1,
) -> dict:
    """Generate one complete video automatically via the main webhook pipeline."""
    job_id = ctx.get("job_id", "")
    logger.info("[Worker] Generating video chat=%s style=%s source=%s theme=%s", chat_id, style_name, source, theme[:80])
    if job_id:
        await _upsert_job_status(job_id, job_type="generate", status="running", started=True)
    try:
        from api.webhooks import run_auto_video_job

        result = await run_auto_video_job(
            chat_id=chat_id,
            theme=theme,
            style_name=style_name,
            choice_idx=choice_idx,
            source=source,
        )
        payload = {"status": "done", **result}
        if job_id:
            await _upsert_job_status(job_id, job_type="generate", status="done", result=payload, finished=True)
        return payload
    except Exception as e:
        logger.exception("[Worker] Video generation failed: %s", e)
        if job_id:
            await _upsert_job_status(job_id, job_type="generate", status="failed", error=str(e)[:500], finished=True)
        raise


async def task_fetch_trending(ctx: dict, platform: str) -> dict:
    """Fetch hot topics from one platform and persist them."""
    logger.info(f"[Worker] Fetching trending from {platform}")
    from db.connection import get_session_factory
    from layers.L1_trending.fetcher import fetch_all

    async with get_session_factory()() as session:
        result = await fetch_all(session, platforms=[platform])
        await session.commit()
    return {"status": "done", "platform": platform, "count": len(result.get(platform, []))}


async def task_daily_batch(ctx: dict) -> dict:
    """Daily auto-production: fetch recommendations and enqueue N jobs."""
    from db.connection import get_session_factory
    from layers.L1_trending.analyzer import analyze_and_recommend
    from layers.L1_trending.fetcher import fetch_all

    chat_id = await runtime_get("default_chat_id")
    batch_size_raw = await runtime_get("daily_batch_size")
    enabled = await runtime_get("daily_batch_enabled")
    if enabled == "0":
        logger.info("[Worker] Daily batch disabled, skip")
        return {"status": "skipped", "reason": "disabled"}
    if not chat_id:
        logger.warning("[Worker] Daily batch skipped: no default chat id configured")
        return {"status": "skipped", "reason": "missing_chat_id"}

    try:
        batch_size = max(1, min(10, int(batch_size_raw or "3")))
    except ValueError:
        batch_size = 3

    async with get_session_factory()() as session:
        await fetch_all(session)
        await session.commit()
        recs = await analyze_and_recommend(session, limit=batch_size)

    if not recs:
        logger.warning("[Worker] Daily batch skipped: no recommendations")
        return {"status": "skipped", "reason": "no_recommendations"}

    job_ids: list[str] = []
    for idx, rec in enumerate(recs, start=1):
        topic = rec.get("title", "")
        angle = rec.get("angle", "")
        theme = topic if not angle else f"{topic}（切入角度：{angle}）"
        job_id = await enqueue_job(
            "task_generate_video",
            chat_id,
            theme,
            "hot_news_commentary",
            "daily_batch",
            1,
            _defer_by=timedelta(seconds=(idx - 1) * 10),
        )
        job_ids.append(job_id)

    return {"status": "queued", "count": len(job_ids), "job_ids": job_ids}


# ── ARQ Worker class (for `arq worker.WorkerSettings`) ────────────────────────

async def task_regenerate_clip(
    ctx: dict,
    clip_id: str,
    new_prompt: str | None = None,
    new_kling_prompt: str | None = None,
    new_first_frame_url: str | None = None,
) -> dict:
    """Regenerate one clip asynchronously with staged progress updates."""
    from layers.L3_visual.regenerate import (
        ClipNotFoundError,
        RegenerateResult,
        regenerate_clip,
    )

    job_id = ctx.get("job_id", "")
    logger.info("[Worker] regenerate_clip clip=%s job=%s", clip_id, job_id)

    if job_id:
        await _upsert_job_status(
            job_id,
            job_type="regenerate_clip",
            status="running",
            started=True,
            progress=5,
            progress_stage="starting",
        )

    try:
        if job_id:
            await _upsert_job_status(
                job_id,
                job_type="regenerate_clip",
                status="running",
                progress=30,
                progress_stage="generating_video",
            )

        result: RegenerateResult = await regenerate_clip(
            clip_id,
            new_prompt=new_prompt,
            new_kling_prompt=new_kling_prompt,
            new_first_frame_url=new_first_frame_url,
        )

        if job_id:
            await _upsert_job_status(
                job_id,
                job_type="regenerate_clip",
                status="running",
                progress=90,
                progress_stage="updating_db",
            )

        payload = {
            "status": "done",
            "clip_id": result.clip_id,
            "new_version": result.new_version,
            "new_video_url": result.new_video_url,
            "new_tail_frame_url": result.new_tail_frame_url,
            "dirty_clip_ids": result.dirty_clip_ids,
            "cost_cny": result.cost_cny,
            "duration_ms": result.duration_ms,
        }

        if job_id:
            await _upsert_job_status(
                job_id,
                job_type="regenerate_clip",
                status="done",
                result=payload,
                progress=100,
                progress_stage="done",
                finished=True,
            )
        return payload

    except ClipNotFoundError:
        logger.warning("[Worker] regenerate_clip not found: %s", clip_id)
        if job_id:
            await _upsert_job_status(
                job_id,
                job_type="regenerate_clip",
                status="failed",
                error=f"clip not found: {clip_id}",
                progress_stage="failed",
                finished=True,
            )
        raise
    except Exception as e:
        logger.exception("[Worker] regenerate_clip failed clip=%s: %s", clip_id, e)
        if job_id:
            await _upsert_job_status(
                job_id,
                job_type="regenerate_clip",
                status="failed",
                error=str(e)[:500],
                progress_stage="failed",
                finished=True,
            )
        raise


class WorkerSettings:
    redis_settings = _get_redis_settings()
    functions = [
        task_generate_video,
        task_fetch_trending,
        task_daily_batch,
        task_regenerate_clip,
    ]
    cron_jobs = [
        # cron(task_daily_batch, hour={9}, minute={0}),  # 暂停：调试完成后恢复
    ]
    max_jobs = 1
    job_timeout = 1800  # 30 minutes per job (Kling polling + FFmpeg + Feishu upload)
    poll_delay = 1.0

    on_startup = None
    on_shutdown = None

    @staticmethod
    async def on_job_start(ctx: dict) -> None:
        logger.info(f"Job started: {ctx.get('job_id')}")

    @staticmethod
    async def on_job_end(ctx: dict) -> None:
        logger.info(f"Job ended: {ctx.get('job_id')}")
