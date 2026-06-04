"""Phase P Sprint P8: service helpers for generation session event trails."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.connection import get_session_factory
from db.models import ClipReviewEvent, GenerationSession

log = logging.getLogger(__name__)

_VALID_STATUSES = frozenset(
    {
        "draft",
        "character_confirmed",
        "scene_confirmed",
        "refimg_confirmed",
        "storyboard_confirmed",
        "in_progress",
        "completed",
        "cancelled",
        "failed",
    }
)
_VALID_STAGES = frozenset({"character", "scene", "refimg", "storyboard", "clip", "final", "session"})
_VALID_DECISIONS = frozenset(
    {"created", "continue", "regen", "cancel", "approved", "rejected", "locked", "completed", "failed"}
)
_ACTIVE_STATUSES = frozenset(
    {"draft", "character_confirmed", "scene_confirmed", "refimg_confirmed", "storyboard_confirmed", "in_progress"}
)


def _factory(session_factory: async_sessionmaker[AsyncSession] | None) -> async_sessionmaker[AsyncSession]:
    return session_factory or get_session_factory()


async def create_session(
    chat_id: str,
    *,
    skill_id: str | None = None,
    theme: str = "",
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> str:
    """Create a generation session and emit session/created."""
    factory = _factory(session_factory)
    async with factory() as db_sess:
        gs = GenerationSession(
            chat_id=chat_id,
            skill_id=skill_id,
            theme=theme or "",
            status="draft",
        )
        db_sess.add(gs)
        await db_sess.flush()
        await db_sess.refresh(gs)
        sid = gs.id
        db_sess.add(
            ClipReviewEvent(
                session_id=sid,
                stage="session",
                decision="created",
                comment=(theme or "")[:200],
            )
        )
        await db_sess.commit()
    log.info("[generation_session] created sid=%s chat=%s skill=%s", sid, chat_id, skill_id)
    return sid


async def get_session(
    session_id: str,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> GenerationSession | None:
    factory = _factory(session_factory)
    async with factory() as db_sess:
        result = await db_sess.execute(select(GenerationSession).where(GenerationSession.id == session_id))
        return result.scalar_one_or_none()


async def find_active_session(
    chat_id: str,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> GenerationSession | None:
    """Return the newest active session for this chat."""
    factory = _factory(session_factory)
    async with factory() as db_sess:
        result = await db_sess.execute(
            select(GenerationSession)
            .where(GenerationSession.chat_id == chat_id)
            .where(GenerationSession.status.in_(list(_ACTIVE_STATUSES)))
            .order_by(GenerationSession.created_at.desc(), GenerationSession.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def update_session(
    session_id: str,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    **fields: Any,
) -> GenerationSession | None:
    """Update whitelisted ORM fields. Status is validated."""
    if "status" in fields and fields["status"] not in _VALID_STATUSES:
        raise ValueError(f"非法 status={fields['status']!r}；允许：{sorted(_VALID_STATUSES)}")

    factory = _factory(session_factory)
    async with factory() as db_sess:
        result = await db_sess.execute(select(GenerationSession).where(GenerationSession.id == session_id))
        gs = result.scalar_one_or_none()
        if gs is None:
            return None
        for key, value in fields.items():
            if hasattr(gs, key):
                setattr(gs, key, value)
        await db_sess.commit()
        await db_sess.refresh(gs)
        return gs


async def lock_character(
    session_id: str,
    character_id: str,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> GenerationSession | None:
    gs = await update_session(
        session_id,
        locked_character_id=character_id,
        status="character_confirmed",
        session_factory=session_factory,
    )
    if gs:
        await emit_event(
            session_id,
            stage="character",
            decision="locked",
            comment=character_id,
            session_factory=session_factory,
        )
    return gs


async def lock_scene(
    session_id: str,
    scene_id: str,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> GenerationSession | None:
    gs = await update_session(
        session_id,
        locked_scene_id=scene_id,
        status="scene_confirmed",
        session_factory=session_factory,
    )
    if gs:
        await emit_event(
            session_id,
            stage="scene",
            decision="locked",
            comment=scene_id,
            session_factory=session_factory,
        )
    return gs


async def lock_storyboard(
    session_id: str,
    storyboard_id: str,
    *,
    plan_id: str | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> GenerationSession | None:
    fields: dict[str, Any] = {"locked_storyboard_id": storyboard_id, "status": "storyboard_confirmed"}
    if plan_id is not None:
        fields["plan_id"] = plan_id
    gs = await update_session(session_id, session_factory=session_factory, **fields)
    if gs:
        await emit_event(
            session_id,
            stage="storyboard",
            decision="locked",
            comment=storyboard_id,
            session_factory=session_factory,
        )
    return gs


async def emit_event(
    session_id: str,
    *,
    stage: str,
    decision: str,
    clip_index: int | None = None,
    comment: str = "",
    hints: list[str] | None = None,
    event_metadata: dict[str, Any] | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> ClipReviewEvent:
    """Record one review event."""
    if stage not in _VALID_STAGES:
        raise ValueError(f"非法 stage={stage!r}；允许：{sorted(_VALID_STAGES)}")
    if decision not in _VALID_DECISIONS:
        raise ValueError(f"非法 decision={decision!r}；允许：{sorted(_VALID_DECISIONS)}")

    factory = _factory(session_factory)
    async with factory() as db_sess:
        event = ClipReviewEvent(
            session_id=session_id,
            stage=stage,
            decision=decision,
            clip_index=clip_index,
            comment=comment or "",
            hints=hints,
            event_metadata=event_metadata,
        )
        db_sess.add(event)
        await db_sess.commit()
        await db_sess.refresh(event)
        log.info(
            "[generation_session] emit event sid=%s stage=%s decision=%s clip=%s hints=%s",
            session_id,
            stage,
            decision,
            clip_index,
            hints,
        )
        return event


async def list_events(
    session_id: str,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> list[ClipReviewEvent]:
    factory = _factory(session_factory)
    async with factory() as db_sess:
        result = await db_sess.execute(
            select(ClipReviewEvent)
            .where(ClipReviewEvent.session_id == session_id)
            .order_by(ClipReviewEvent.created_at.asc(), ClipReviewEvent.id.asc())
        )
        return list(result.scalars().all())
