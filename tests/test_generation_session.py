from __future__ import annotations

import pytest
from sqlalchemy import BigInteger, create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.models import Base, ClipReviewEvent, GenerationSession
from layers.L2_creative.generation_session import (
    create_session,
    emit_event,
    find_active_session,
    get_session,
    list_events,
    lock_character,
    lock_scene,
    lock_storyboard,
    update_session,
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

    Base.metadata.create_all(engine, tables=[GenerationSession.__table__, ClipReviewEvent.__table__])
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

        def delete(self, obj):
            self._session.delete(obj)

    class _Factory:
        bind = engine

        def __call__(self):
            return _AsyncSessionWrapper()

    return _Factory()


@pytest.mark.asyncio
async def test_create_session_returns_id_and_writes_row(session_factory):
    sid = await create_session("chat-1", skill_id="cinematic_narrative", theme="AI 视频", session_factory=session_factory)

    assert len(sid) == 16
    gs = await get_session(sid, session_factory=session_factory)
    assert gs is not None
    assert gs.chat_id == "chat-1"
    assert gs.skill_id == "cinematic_narrative"
    assert gs.theme == "AI 视频"
    assert gs.status == "draft"


@pytest.mark.asyncio
async def test_create_session_also_emits_session_created_event(session_factory):
    sid = await create_session("chat-1", theme="主题", session_factory=session_factory)

    events = await list_events(sid, session_factory=session_factory)
    assert len(events) == 1
    assert events[0].stage == "session"
    assert events[0].decision == "created"
    assert events[0].comment == "主题"


@pytest.mark.asyncio
async def test_get_session_returns_none_for_missing_id(session_factory):
    assert await get_session("NOPE", session_factory=session_factory) is None


@pytest.mark.asyncio
async def test_get_session_returns_orm_instance(session_factory):
    sid = await create_session("chat-1", session_factory=session_factory)

    gs = await get_session(sid, session_factory=session_factory)
    assert isinstance(gs, GenerationSession)


@pytest.mark.asyncio
async def test_find_active_session_returns_latest_active(session_factory):
    completed = await create_session("chat-1", theme="old", session_factory=session_factory)
    await update_session(completed, status="completed", session_factory=session_factory)
    active = await create_session("chat-1", theme="new", session_factory=session_factory)

    found = await find_active_session("chat-1", session_factory=session_factory)
    assert found is not None
    assert found.id == active


@pytest.mark.asyncio
async def test_find_active_session_skips_completed(session_factory):
    sid = await create_session("chat-1", session_factory=session_factory)
    await update_session(sid, status="completed", session_factory=session_factory)

    assert await find_active_session("chat-1", session_factory=session_factory) is None


@pytest.mark.asyncio
async def test_update_session_status_to_completed(session_factory):
    sid = await create_session("chat-1", session_factory=session_factory)

    gs = await update_session(sid, status="completed", session_factory=session_factory)
    assert gs is not None
    assert gs.status == "completed"


@pytest.mark.asyncio
async def test_update_session_rejects_invalid_status_raises_value_error(session_factory):
    sid = await create_session("chat-1", session_factory=session_factory)

    with pytest.raises(ValueError, match="status"):
        await update_session(sid, status="half_done", session_factory=session_factory)


@pytest.mark.asyncio
async def test_lock_character_updates_field_and_status_and_emits_event(session_factory):
    sid = await create_session("chat-1", session_factory=session_factory)

    gs = await lock_character(sid, "su_wan", session_factory=session_factory)
    events = await list_events(sid, session_factory=session_factory)

    assert gs is not None
    assert gs.locked_character_id == "su_wan"
    assert gs.status == "character_confirmed"
    assert events[-1].stage == "character"
    assert events[-1].decision == "locked"


@pytest.mark.asyncio
async def test_lock_scene_updates_field_and_status_and_emits_event(session_factory):
    sid = await create_session("chat-1", session_factory=session_factory)

    gs = await lock_scene(sid, "coffee_shop", session_factory=session_factory)
    events = await list_events(sid, session_factory=session_factory)

    assert gs is not None
    assert gs.locked_scene_id == "coffee_shop"
    assert gs.status == "scene_confirmed"
    assert events[-1].stage == "scene"


@pytest.mark.asyncio
async def test_lock_storyboard_with_plan_id(session_factory):
    sid = await create_session("chat-1", session_factory=session_factory)

    gs = await lock_storyboard(sid, "SB001", plan_id="P001", session_factory=session_factory)
    events = await list_events(sid, session_factory=session_factory)

    assert gs is not None
    assert gs.locked_storyboard_id == "SB001"
    assert gs.plan_id == "P001"
    assert gs.status == "storyboard_confirmed"
    assert events[-1].stage == "storyboard"


@pytest.mark.asyncio
async def test_emit_event_basic(session_factory):
    sid = await create_session("chat-1", session_factory=session_factory)

    event = await emit_event(sid, stage="clip", decision="continue", clip_index=1, session_factory=session_factory)

    assert event.id >= 1
    assert event.stage == "clip"
    assert event.decision == "continue"
    assert event.clip_index == 1


@pytest.mark.asyncio
async def test_emit_event_with_hints_and_metadata(session_factory):
    sid = await create_session("chat-1", session_factory=session_factory)

    event = await emit_event(
        sid,
        stage="clip",
        decision="regen",
        clip_index=2,
        comment="人物近一点",
        hints=["closer_shot"],
        event_metadata={"regen_count": 1, "duration_sec": 5},
        session_factory=session_factory,
    )

    assert event.hints == ["closer_shot"]
    assert event.event_metadata == {"regen_count": 1, "duration_sec": 5}


@pytest.mark.asyncio
async def test_emit_event_invalid_stage_raises(session_factory):
    sid = await create_session("chat-1", session_factory=session_factory)

    with pytest.raises(ValueError, match="stage"):
        await emit_event(sid, stage="bad", decision="continue", session_factory=session_factory)


@pytest.mark.asyncio
async def test_emit_event_invalid_decision_raises(session_factory):
    sid = await create_session("chat-1", session_factory=session_factory)

    with pytest.raises(ValueError, match="decision"):
        await emit_event(sid, stage="clip", decision="maybe", session_factory=session_factory)


@pytest.mark.asyncio
async def test_list_events_orders_by_created_then_id(session_factory):
    sid = await create_session("chat-1", session_factory=session_factory)
    await emit_event(sid, stage="clip", decision="continue", clip_index=1, session_factory=session_factory)
    await emit_event(sid, stage="final", decision="completed", session_factory=session_factory)

    events = await list_events(sid, session_factory=session_factory)

    assert [event.decision for event in events] == ["created", "continue", "completed"]
    assert [event.id for event in events] == sorted(event.id for event in events)


@pytest.mark.asyncio
async def test_full_lifecycle_create_lock_emit_complete(session_factory):
    sid = await create_session("chat-1", skill_id="knowledge", theme="Agent", session_factory=session_factory)
    await lock_character(sid, "su_wan", session_factory=session_factory)
    await lock_scene(sid, "office", session_factory=session_factory)
    await lock_storyboard(sid, "SB001", plan_id="P001", session_factory=session_factory)
    await update_session(sid, status="in_progress", session_factory=session_factory)
    await emit_event(sid, stage="clip", decision="continue", clip_index=1, session_factory=session_factory)
    await update_session(sid, status="completed", session_factory=session_factory)
    await emit_event(sid, stage="final", decision="completed", session_factory=session_factory)

    gs = await get_session(sid, session_factory=session_factory)
    events = await list_events(sid, session_factory=session_factory)

    assert gs is not None
    assert gs.status == "completed"
    assert gs.locked_character_id == "su_wan"
    assert events[-1].decision == "completed"


@pytest.mark.asyncio
async def test_cascade_delete_session_drops_its_events(session_factory):
    sid = await create_session("chat-1", session_factory=session_factory)
    await emit_event(sid, stage="clip", decision="continue", session_factory=session_factory)

    async with session_factory() as session:
        result = await session.execute(select(GenerationSession).where(GenerationSession.id == sid))
        gs = result.scalar_one()
        session.delete(gs)
        await session.commit()

    events = await list_events(sid, session_factory=session_factory)
    assert events == []
