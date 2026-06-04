"""
myAiVideos v3 — 企业级重建入口
Phase 3: 数据驱动 + 基础设施 (PostgreSQL + Redis + 热搜)
"""
import logging
import uuid

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request

from config.settings import get_settings
from core.langfuse_client import flush as langfuse_flush
from core.langfuse_client import get_langfuse_client
from core.logging_setup import setup_logging
from core.trace_context import reset_current_trace_id, set_current_trace_id
from api.webhooks import router as webhook_router
from api.storyboard_api import router as storyboard_router
from api.clip_api import router as clip_router

setup_logging("orchestrator")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──
    cfg = get_settings()
    cfg.ensure_dirs()

    from layers.L2_creative.style_engine import load_all_templates
    templates = load_all_templates()
    log.info("已加载 %d 个风格模板: %s", len(templates), list(templates.keys()))

    # Initialize PostgreSQL
    from db.connection import init_db
    await init_db()
    log.info("PostgreSQL 连接就绪")

    # Initialize Redis
    from core.scheduler import get_redis
    redis = await get_redis()
    await redis.ping()
    get_langfuse_client()
    log.info("Redis 连接就绪")

    # Schedule periodic trending fetch
    from core.scheduler import enqueue_job
    await enqueue_job("task_fetch_trending", "weibo")
    await enqueue_job("task_fetch_trending", "douyin")
    await enqueue_job("task_fetch_trending", "bilibili")
    log.info("热搜抓取任务已入队")

    yield

    # ── Shutdown ──
    from db.connection import close_db
    from core.scheduler import close_redis
    langfuse_flush()
    await close_redis()
    await close_db()
    log.info("连接已关闭")


app = FastAPI(title="myAiVideos", version="3.0.0", lifespan=lifespan)


@app.middleware("http")
async def trace_id_propagation(request: Request, call_next):
    """部署日补：透传 Java gateway 注入的 X-Trace-Id 到 Python 日志 + 响应头。

    M5/M9 生产观测演示：让 `grep <trace_id>` 能跨 Java + Python 两边日志找到同一条请求。
    """
    trace_id = request.headers.get("X-Trace-Id", "") or uuid.uuid4().hex[:16]
    token = set_current_trace_id(trace_id)
    try:
        log.info("[trace=%s] %s %s", trace_id, request.method, request.url.path)
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response
    finally:
        reset_current_trace_id(token)


app.include_router(webhook_router)
app.include_router(storyboard_router)
app.include_router(clip_router)


@app.get("/health")
async def health():
    from core.scheduler import get_redis
    from db.connection import get_engine
    try:
        redis = await get_redis()
        await redis.ping()
        redis_ok = True
    except Exception:
        redis_ok = False

    return {
        "status": "ok",
        "version": "3.0.0",
        "redis": "connected" if redis_ok else "disconnected",
        "database": "configured",
    }
