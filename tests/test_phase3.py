"""
Phase 3 integration tests — Database, Redis, Trending, Distribution.
"""

import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock

# ══════════════════════════════════════════════════════════════════════════════
# Test: DB Models can be imported and instantiated
# ══════════════════════════════════════════════════════════════════════════════


def test_models_import():
    from db.models import (
        Base, Plan, OperatorStats, Feedback, Job,
        TrendingTopic, PublishRecord, StyleProfile,
    )
    assert Plan.__tablename__ == "plans"
    assert TrendingTopic.__tablename__ == "trending_topics"
    assert PublishRecord.__tablename__ == "publish_records"


def test_plan_creation():
    from db.models import Plan
    plan = Plan(id="ABC123", mode="creative", theme="猫咪上班")
    assert plan.id == "ABC123"
    assert plan.mode == "creative"
    assert plan.status == "scripted"


def test_trending_topic_creation():
    from db.models import TrendingTopic
    topic = TrendingTopic(platform="weibo", rank=1, title="测试热搜", hot_score=1000000.0)
    assert topic.platform == "weibo"
    assert topic.hot_score == 1000000.0


# ══════════════════════════════════════════════════════════════════════════════
# Test: Settings includes Phase 3 fields
# ══════════════════════════════════════════════════════════════════════════════


def test_settings_phase3_fields():
    from config.settings import Settings
    s = Settings(
        database_url="postgresql+asyncpg://test:test@localhost/test",
        redis_url="redis://localhost:6379/0",
    )
    assert "asyncpg" in s.database_url
    assert s.redis_url.startswith("redis://")
    assert s.trending_fetch_interval_min == 30
    assert "douyin" in s.trending_platforms


# ══════════════════════════════════════════════════════════════════════════════
# Test: State manager interface
# ══════════════════════════════════════════════════════════════════════════════


def test_state_manager_import():
    from core.state import StateManager, PLAN_STATUS
    assert "scripted" in PLAN_STATUS
    assert "pending_confirm" in PLAN_STATUS
    assert "published" in PLAN_STATUS


# ══════════════════════════════════════════════════════════════════════════════
# Test: Scheduler / Redis module
# ══════════════════════════════════════════════════════════════════════════════


def test_scheduler_import():
    from core.scheduler import (
        get_redis, close_redis, session_set, session_get,
        enqueue_job, WorkerSettings,
    )
    assert WorkerSettings.max_jobs == 3
    assert WorkerSettings.job_timeout == 600
    assert len(WorkerSettings.functions) == 3


# ══════════════════════════════════════════════════════════════════════════════
# Test: Trending fetcher module
# ══════════════════════════════════════════════════════════════════════════════


def test_fetcher_import():
    from layers.L1_trending.fetcher import (
        fetch_all, get_latest_trending, format_trending_for_feishu,
        _fetch_weibo, _fetch_douyin, _fetch_bilibili,
    )
    assert callable(fetch_all)
    assert callable(_fetch_weibo)


def test_analyzer_import():
    from layers.L1_trending.analyzer import (
        analyze_and_recommend, format_recommendations_for_feishu,
    )
    assert callable(analyze_and_recommend)


def test_recommender_import():
    from layers.L1_trending.recommender import (
        get_successful_themes, get_topic_frequency, should_auto_generate,
    )
    assert callable(should_auto_generate)


# ══════════════════════════════════════════════════════════════════════════════
# Test: Distribution (Feishu notification — auto-publish deferred)
# ══════════════════════════════════════════════════════════════════════════════


def test_build_publish_card():
    from layers.L6_distribution.publisher import build_publish_card
    msg = build_publish_card(
        title="测试视频",
        video_path="/output/test.mp4",
        tags=["猫咪", "搞笑"],
        cover_path="/output/cover.jpg",
    )
    assert "测试视频" in msg
    assert "/output/test.mp4" in msg
    assert "#猫咪" in msg
    assert "手动发布" in msg


# ══════════════════════════════════════════════════════════════════════════════
# Test: Docker Compose has all services
# ══════════════════════════════════════════════════════════════════════════════


def test_docker_compose_services():
    import yaml
    from pathlib import Path
    compose_path = Path(__file__).parent.parent / "docker-compose.yaml"
    with open(compose_path) as f:
        config = yaml.safe_load(f)
    services = config["services"]
    assert "postgres" in services
    assert "redis" in services
    assert "orchestrator" in services
    assert "worker" in services


# ══════════════════════════════════════════════════════════════════════════════
# Test: Webhook has Phase 3 commands in HELP_TEXT
# ══════════════════════════════════════════════════════════════════════════════


def test_webhook_help_includes_phase3():
    from api.webhooks import HELP_TEXT
    assert "热搜" in HELP_TEXT
    assert "热门" in HELP_TEXT
    assert "发布" in HELP_TEXT


# ══════════════════════════════════════════════════════════════════════════════
# Test: Alembic migration exists
# ══════════════════════════════════════════════════════════════════════════════


def test_migration_exists():
    from pathlib import Path
    migration = Path(__file__).parent.parent / "db" / "migrations" / "versions" / "001_initial_schema.py"
    assert migration.exists()
    content = migration.read_text()
    assert "plans" in content
    assert "trending_topics" in content
    assert "publish_records" in content
