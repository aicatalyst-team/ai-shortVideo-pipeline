from __future__ import annotations

import pytest
from sqlalchemy import BigInteger, create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.models import (
    Base,
    ClipReviewEvent,
    CreatorMemory,
    FailRecord,
    GenerationSession,
)
from layers.L2_creative.generation_session import create_session, emit_event, lock_character, lock_storyboard
from layers.L2_creative.rating_service import (
    MIN_SCORE_FOR_MEMORY,
    VALID_ERROR_CODES,
    parse_score_reply,
    propose_memory_from_session,
    record_fail,
    record_final_score,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(_type, _compiler, **_kwargs):
    return "INTEGER"


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(
        engine,
        tables=[
            GenerationSession.__table__,
            ClipReviewEvent.__table__,
            CreatorMemory.__table__,
            FailRecord.__table__,
        ],
    )
    sync_factory = sessionmaker(engine, expire_on_commit=False)

    class _AsyncSessionWrapper:
        def __init__(self):
            self._session = sync_factory()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            self._session.close()
            return False

        async def execute(self, statement):
            return self._session.execute(statement)

        async def flush(self):
            self._session.flush()

        async def refresh(self, obj):
            self._session.refresh(obj)

        async def commit(self):
            self._session.commit()

        def add(self, obj):
            self._session.add(obj)

    class _Factory:
        bind = engine

        def __call__(self):
            return _AsyncSessionWrapper()

    return _Factory()


async def _seed_session(factory, *, skill_id="cinematic_narrative", theme="AI 编程效率"):
    sid = await create_session("chat-1", skill_id=skill_id, theme=theme, session_factory=factory)
    await lock_character(sid, "su_wan", session_factory=factory)
    await lock_storyboard(sid, "SB001", plan_id="P001", session_factory=factory)
    await emit_event(
        sid,
        stage="clip",
        decision="regen",
        clip_index=1,
        comment="人物近一点",
        hints=["closer_shot", "no_text"],
        session_factory=factory,
    )
    await emit_event(sid, stage="clip", decision="continue", clip_index=1, session_factory=factory)
    return sid


def test_parse_pure_number():
    assert parse_score_reply("8") == 8


def test_parse_with_score_prefix():
    assert parse_score_reply("评分 8") == 8


def test_parse_with_unit_fen():
    assert parse_score_reply("8分") == 8


def test_parse_full_width_punctuation():
    assert parse_score_reply("评分：10") == 10


def test_parse_rejects_zero_and_negative():
    assert parse_score_reply("0") is None
    assert parse_score_reply("-1") is None


def test_parse_rejects_above_10():
    assert parse_score_reply("11") is None


def test_parse_returns_none_for_empty_or_nonnumeric():
    assert parse_score_reply("") is None
    assert parse_score_reply("挺好") is None


@pytest.mark.asyncio
async def test_record_score_below_6_skips_memory(session_factory):
    sid = await _seed_session(session_factory)

    outcome = await record_final_score(sid, 5, session_factory=session_factory)

    assert outcome.score == 5
    assert not outcome.memory_written
    assert "分数 <" in outcome.reason_skipped


@pytest.mark.asyncio
async def test_record_score_6_writes_memory_with_confidence_06(session_factory):
    sid = await _seed_session(session_factory)

    outcome = await record_final_score(sid, 6, session_factory=session_factory)

    assert outcome.memory_written
    async with session_factory() as session:
        result = await session.execute(select(CreatorMemory).where(CreatorMemory.id == outcome.memory_id))
        memory = result.scalar_one()
        assert memory.confidence == 0.6


@pytest.mark.asyncio
async def test_record_score_10_writes_memory_with_confidence_10(session_factory):
    sid = await _seed_session(session_factory)

    outcome = await record_final_score(sid, 10, session_factory=session_factory)

    async with session_factory() as session:
        result = await session.execute(select(CreatorMemory).where(CreatorMemory.id == outcome.memory_id))
        memory = result.scalar_one()
        assert memory.confidence == 1.0


@pytest.mark.asyncio
async def test_record_score_invalid_raises_value_error(session_factory):
    sid = await _seed_session(session_factory)

    with pytest.raises(ValueError, match="score"):
        await record_final_score(sid, 0, session_factory=session_factory)


@pytest.mark.asyncio
async def test_record_score_missing_session_returns_skipped_outcome(session_factory):
    outcome = await record_final_score("NOPE", 8, session_factory=session_factory)

    assert not outcome.memory_written
    assert outcome.reason_skipped == "session 不存在"


@pytest.mark.asyncio
async def test_propose_memory_aggregates_hints_from_events(session_factory):
    sid = await _seed_session(session_factory)

    memory = await propose_memory_from_session(sid, score=8, session_factory=session_factory)

    assert memory is not None
    assert "closer_shot" in memory.prompt_rule
    assert "no_text" in memory.prompt_rule
    assert memory.source_ref["hints"] == ["closer_shot", "no_text"]


@pytest.mark.asyncio
async def test_propose_memory_includes_skill_and_character_in_source_ref(session_factory):
    sid = await _seed_session(session_factory)

    memory = await propose_memory_from_session(sid, score=8, session_factory=session_factory)

    assert memory is not None
    assert memory.style_name == "cinematic_narrative"
    assert memory.source_ref["skill_id"] == "cinematic_narrative"
    assert memory.source_ref["locked_character_id"] == "su_wan"


@pytest.mark.asyncio
async def test_propose_memory_handles_session_without_events(session_factory):
    sid = await create_session("chat-2", skill_id="knowledge", theme="科普", session_factory=session_factory)

    memory = await propose_memory_from_session(sid, score=7, session_factory=session_factory)

    assert memory is not None
    assert "Skill：knowledge" in memory.content
    assert "clip_events=" in memory.evidence


@pytest.mark.asyncio
async def test_record_fail_with_valid_code(session_factory):
    sid = await _seed_session(session_factory)

    record = await record_fail(
        sid,
        stage="clip",
        error_code="KLING_FAILED",
        error_message="kling 500",
        session_factory=session_factory,
    )

    assert record.error_code == "KLING_FAILED"
    assert "可灵" in record.suggestion


@pytest.mark.asyncio
async def test_record_fail_invalid_code_falls_back_to_other(session_factory):
    sid = await _seed_session(session_factory)

    record = await record_fail(sid, stage="clip", error_code="WHAT", session_factory=session_factory)

    assert record.error_code == "OTHER"


@pytest.mark.asyncio
async def test_record_fail_session_id_none_allowed(session_factory):
    record = await record_fail(None, stage="session", error_code="OTHER", session_factory=session_factory)

    assert record.session_id is None
    assert record.error_code == "OTHER"


@pytest.mark.asyncio
async def test_record_fail_default_suggestion_per_code(session_factory):
    record = await record_fail(None, stage="final", error_code="AV_DRIFT", session_factory=session_factory)

    assert "旁白" in record.suggestion


@pytest.mark.asyncio
async def test_record_fail_truncates_long_message_to_500(session_factory):
    record = await record_fail(
        None,
        stage="session",
        error_code="OTHER",
        error_message="x" * 600,
        session_factory=session_factory,
    )

    assert len(record.error_message) == 500


def test_constants_are_exposed():
    assert len(VALID_ERROR_CODES) == 7
    assert MIN_SCORE_FOR_MEMORY == 6
