"""Phase P Sprint P9: final user score, memory deposition, and fail records."""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.connection import get_session_factory
from db.models import ClipReviewEvent, CreatorMemory, FailRecord, GenerationSession

log = logging.getLogger(__name__)

VALID_ERROR_CODES = frozenset(
    {
        "PROMPT_TOO_LONG",
        "TTS_TIMEOUT",
        "KLING_FAILED",
        "TEXT_LIKE_DETECTED",
        "AV_DRIFT",
        "COST_LIMIT",
        "OTHER",
    }
)

MIN_SCORE_FOR_MEMORY: int = 6
MIN_SCORE: int = 1
MAX_SCORE: int = 10


class ScoreOutcome(BaseModel):
    """Final score write result for Feishu feedback."""

    session_id: str
    score: int
    memory_written: bool = False
    memory_id: str | None = None
    reason_skipped: str = ""

    def to_feishu_line(self) -> str:
        if self.memory_written:
            return f"⭐ 评分 {self.score}/10 已记入偏好库（memory={self.memory_id}）。下次类似生成会参考。"
        return f"评分 {self.score}/10 已记录。未进偏好库：{self.reason_skipped}"


def _factory(session_factory: async_sessionmaker[AsyncSession] | None) -> async_sessionmaker[AsyncSession]:
    return session_factory or get_session_factory()


def parse_score_reply(text: str) -> int | None:
    """Parse '8', '8分', '评分 8', '评分：8', '8/10', '★8' into an int score."""
    raw = (text or "").strip()
    if not raw:
        return None
    match = re.search(r"(?<![\d-])(10|[1-9])(?!\d)", raw)
    if not match:
        return None
    score = int(match.group(1))
    if score < MIN_SCORE or score > MAX_SCORE:
        return None
    return score


async def record_final_score(
    session_id: str,
    score: int,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> ScoreOutcome:
    """Write final_score; score >= 6 also creates an approved CreatorMemory."""
    if score < MIN_SCORE or score > MAX_SCORE:
        raise ValueError(f"score={score} 超出 [{MIN_SCORE},{MAX_SCORE}]")

    factory = _factory(session_factory)
    async with factory() as db_sess:
        result = await db_sess.execute(select(GenerationSession).where(GenerationSession.id == session_id))
        gs = result.scalar_one_or_none()
        if gs is None:
            return ScoreOutcome(
                session_id=session_id,
                score=score,
                memory_written=False,
                reason_skipped="session 不存在",
            )
        gs.final_score = score
        await db_sess.commit()

    if score < MIN_SCORE_FOR_MEMORY:
        return ScoreOutcome(
            session_id=session_id,
            score=score,
            memory_written=False,
            reason_skipped=f"分数 < {MIN_SCORE_FOR_MEMORY} 阈值",
        )

    memory = await propose_memory_from_session(session_id, score=score, session_factory=session_factory)
    if memory is None:
        return ScoreOutcome(
            session_id=session_id,
            score=score,
            memory_written=False,
            reason_skipped="propose_memory 返回空",
        )
    return ScoreOutcome(session_id=session_id, score=score, memory_written=True, memory_id=memory.id)


async def propose_memory_from_session(
    session_id: str,
    *,
    score: int,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> CreatorMemory | None:
    """Turn a completed generation session and review trail into CreatorMemory."""
    factory = _factory(session_factory)
    async with factory() as db_sess:
        result = await db_sess.execute(select(GenerationSession).where(GenerationSession.id == session_id))
        gs = result.scalar_one_or_none()
        if gs is None:
            log.warning("[rating] propose_memory session=%s not found", session_id)
            return None

        events_result = await db_sess.execute(
            select(ClipReviewEvent)
            .where(ClipReviewEvent.session_id == session_id)
            .order_by(ClipReviewEvent.created_at.asc(), ClipReviewEvent.id.asc())
        )
        events = list(events_result.scalars().all())

        regen_count = sum(1 for event in events if event.stage == "clip" and event.decision == "regen")
        continue_count = sum(1 for event in events if event.stage == "clip" and event.decision == "continue")
        hints_seen: set[str] = set()
        for event in events:
            for hint in event.hints or []:
                hints_seen.add(str(hint))
        hints_sorted = sorted(hints_seen)

        content_parts = []
        if gs.theme:
            content_parts.append(f"主题：{gs.theme[:80]}")
        if gs.skill_id:
            content_parts.append(f"Skill：{gs.skill_id}")
        if gs.locked_character_id:
            content_parts.append(f"角色：{gs.locked_character_id}")
        if hints_sorted:
            content_parts.append(f"用户修订偏好：{','.join(hints_sorted)}")
        content = " | ".join(content_parts) or "（无上下文）"

        prompt_rule_parts = []
        if hints_sorted:
            prompt_rule_parts.append(f"类似生成应优先满足 hints: {hints_sorted}")
        if gs.skill_id:
            prompt_rule_parts.append(f"默认使用 Skill={gs.skill_id}")
        prompt_rule = "；".join(prompt_rule_parts) or "保持当前生成参数不变"
        evidence = f"score={score}/10, continue={continue_count}, regen={regen_count}, clip_events={len(events)}"

        memory = CreatorMemory(
            id=uuid.uuid4().hex[:12].upper(),
            owner_id=gs.chat_id or "global",
            scope="style",
            style_name=gs.skill_id or "global",
            type="session_outcome",
            content=content,
            prompt_rule=prompt_rule,
            evidence=evidence,
            confidence=score / float(MAX_SCORE),
            status="approved",
            source_ref={
                "session_id": gs.id,
                "skill_id": gs.skill_id,
                "plan_id": gs.plan_id,
                "locked_character_id": gs.locked_character_id,
                "locked_storyboard_id": gs.locked_storyboard_id,
                "regen_count": regen_count,
                "continue_count": continue_count,
                "hints": hints_sorted,
            },
            approved_at=datetime.utcnow(),
        )
        db_sess.add(memory)
        await db_sess.commit()
        await db_sess.refresh(memory)
        log.info("[rating] memory written id=%s session=%s score=%d", memory.id, session_id, score)
        return memory


async def record_fail(
    session_id: str | None,
    *,
    stage: str,
    error_code: str,
    error_message: str = "",
    suggestion: str = "",
    metadata: dict[str, Any] | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> FailRecord:
    """Record one structured failure row. Unknown codes fall back to OTHER."""
    if error_code not in VALID_ERROR_CODES:
        log.warning("[rating] invalid error_code=%r, fallback to OTHER", error_code)
        error_code = "OTHER"

    factory = _factory(session_factory)
    async with factory() as db_sess:
        record = FailRecord(
            session_id=session_id,
            stage=stage,
            error_code=error_code,
            error_message=(error_message or "")[:500],
            suggestion=suggestion or _default_suggestion(error_code),
            event_metadata=metadata,
        )
        db_sess.add(record)
        await db_sess.commit()
        await db_sess.refresh(record)
        return record


def _default_suggestion(error_code: str) -> str:
    return {
        "PROMPT_TOO_LONG": "缩短旁白到该段视频时长允许范围（5s≤40字 / 10s≤82字）",
        "TTS_TIMEOUT": "重新生成本段；如持续超时检查火山 TTS 配额",
        "KLING_FAILED": "重新生成本段；如持续失败检查可灵 API 余额或模型可用性",
        "TEXT_LIKE_DETECTED": "改 image_prompt 加 negative 'no text'；或重新生成首帧",
        "AV_DRIFT": "缩短旁白字数或拆段；P3 visual_planner 兜底已选 10s 仍超时",
        "COST_LIMIT": "本视频成本已超阈值；建议接受当前结果或换更便宜模型",
        "OTHER": "查 log 排查；如持续触发请开 issue",
    }.get(error_code, "查 log 排查")
