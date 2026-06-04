from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import select

from config.settings import get_settings
from db.connection import get_session_factory
from db.models import Clip, FrameAsset, Storyboard
from layers.L2_creative.schemas import SceneShot
from layers.L2_creative.style_engine import get_template
from layers.L3_visual.image_to_video import extract_last_frame, generate_clip

log = logging.getLogger(__name__)


class RegenerateResult(BaseModel):
    clip_id: str
    new_version: int
    new_video_url: str
    new_tail_frame_url: str | None
    dirty_clip_ids: list[str]
    cost_cny: float
    duration_ms: int


class ClipNotFoundError(Exception):
    pass


async def regenerate_clip(
    clip_id: str,
    *,
    new_prompt: str | None = None,
    new_kling_prompt: str | None = None,
    new_first_frame_url: str | None = None,
    session_factory=None,
) -> RegenerateResult:
    if new_prompt is None and new_kling_prompt is None and new_first_frame_url is None:
        raise ValueError("至少需要一个变更参数")

    factory = session_factory or get_session_factory()

    async with factory() as session:
        row = await session.execute(
            select(Clip, Storyboard)
            .join(Storyboard, Storyboard.id == Clip.storyboard_id)
            .where(Clip.id == clip_id)
        )
        pair = row.first()
        if pair is None:
            raise ClipNotFoundError(clip_id)
        clip, storyboard = pair

        prompt, kling_prompt, duration_sec = _resolve_clip_context(clip)
        style_name = storyboard.style_name or "hot_news_commentary"
        old_version = int(clip.version or 1)
        old_video_url = clip.video_url or ""

    prompt_to_use = new_prompt if new_prompt is not None else prompt
    kling_prompt_to_use = new_kling_prompt if new_kling_prompt is not None else kling_prompt

    # (2026-05-21):
    # 工单原话："旧首帧从 frame_assets 读，新首帧从入参读"。
    # 早期实现遗漏了"旧首帧 fallback"，导致只改 prompt 时 generate_clip 会重新文生图，
    # 画面与原段彻底断开 → dirty 传播形同虚设 → "单段修复"卖点塌房。
    # 修补：new_first_frame_url 为空时，从 frame_assets 查 clip_id + kind='first' 最新一张。
    if new_first_frame_url is not None:
        first_frame_path = _resolve_first_frame_path(new_first_frame_url)
    else:
        first_frame_path = await _load_existing_first_frame(factory, clip_id)
        if first_frame_path:
            log.info("[regenerate_clip] reusing existing first_frame for clip=%s: %s",
                     clip_id, first_frame_path)
        else:
            log.warning("[regenerate_clip] clip=%s has no existing first_frame; "
                        "generate_clip will redraw from prompt (画面可能与原段断开)", clip_id)

    style = get_template(style_name)

    temp_dir = Path(tempfile.mkdtemp(prefix=f"regen_{clip_id}_"))
    output_path = temp_dir / f"{clip_id}_v{old_version + 1}.mp4"
    tail_path = temp_dir / f"{clip_id}_tail_v{old_version + 1}.png"

    started_at = time.perf_counter()
    try:
        video_result = await generate_clip(
            image_prompt=prompt_to_use,
            kling_prompt=kling_prompt_to_use,
            output_path=str(output_path),
            style=style,
            duration_sec=duration_sec,
            first_frame_path=first_frame_path,
        )
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    except Exception:
        await _mark_clip_failed(factory, clip_id)
        raise

    local_video_path = video_result.local_path or str(output_path)
    tail_frame_url = None
    try:
        tail_frame_url = extract_last_frame(local_video_path, str(tail_path))
    except Exception as exc:
        log.warning("[regenerate_clip] extract_last_frame failed for clip_id=%s: %s", clip_id, exc)

    new_video_url = video_result.url or local_video_path
    cost_cny = _estimate_clip_cost(duration_sec)

    async with factory() as session:
        clip_db = await session.get(Clip, clip_id)
        if clip_db is None:
            raise ClipNotFoundError(clip_id)

        dirty_result = await session.execute(
            select(Clip)
            .where(Clip.storyboard_id == clip_db.storyboard_id, Clip.seq > clip_db.seq)
            .order_by(Clip.seq)
        )
        later_clips = dirty_result.scalars().all()

        dirty_clip_ids: list[str] = []
        for later_clip in later_clips:
            if later_clip.status == "dirty":
                continue
            later_clip.status = "dirty"
            dirty_clip_ids.append(later_clip.id)

        if old_video_url:
            session.add(
                FrameAsset(
                    clip_id=clip_db.id,
                    node_id=clip_db.node_id,
                    kind="archived_video",
                    url=old_video_url,
                    source="archived",
                    asset_metadata={"from_version": clip_db.version, "reason": "regenerate_clip"},
                )
            )

        if tail_frame_url:
            session.add(
                FrameAsset(
                    clip_id=clip_db.id,
                    node_id=clip_db.node_id,
                    kind="tail_frame",
                    url=tail_frame_url,
                    source="generated",
                    asset_metadata={"version": clip_db.version + 1},
                )
            )

        clip_db.prompt = prompt_to_use
        clip_db.kling_prompt = kling_prompt_to_use
        clip_db.video_url = new_video_url
        clip_db.status = "ready"
        clip_db.model = video_result.model or clip_db.model
        clip_db.cost_cny = cost_cny
        clip_db.duration_ms = elapsed_ms
        clip_db.version = clip_db.version + 1

        await session.commit()

        return RegenerateResult(
            clip_id=clip_db.id,
            new_version=clip_db.version,
            new_video_url=new_video_url,
            new_tail_frame_url=tail_frame_url,
            dirty_clip_ids=dirty_clip_ids,
            cost_cny=cost_cny,
            duration_ms=elapsed_ms,
        )


def _resolve_clip_context(clip: Clip) -> tuple[str, str, int]:
    if not clip.r_metadata:
        log.warning("[regenerate_clip] clip_id=%s missing r_metadata, fallback to clip fields", clip.id)
        return clip.prompt or "", clip.kling_prompt or "", int(clip.duration_sec or 5)

    metadata = clip.r_metadata if isinstance(clip.r_metadata, dict) else {}
    prompt = clip.prompt or ""
    kling_prompt = clip.kling_prompt or metadata.get("kling_prompt", "") or ""
    duration_sec = int(clip.duration_sec or 5)

    try:
        shot = SceneShot.model_validate(metadata)
        duration_sec = max(1, int(round(shot.estimated_duration_sec)))
    except Exception as exc:
        log.warning("[regenerate_clip] clip_id=%s invalid r_metadata, fallback partial fields: %s", clip.id, exc)
        raw_duration = metadata.get("estimated_duration_sec")
        if raw_duration is not None:
            try:
                duration_sec = max(1, int(round(float(raw_duration))))
            except (TypeError, ValueError):
                duration_sec = int(clip.duration_sec or 5)

    return prompt, kling_prompt, duration_sec


def _resolve_first_frame_path(first_frame: str | None) -> str | None:
    if not first_frame:
        return None
    if first_frame.startswith("http://") or first_frame.startswith("https://"):
        log.info("[regenerate_clip] skip downloading remote first frame: %s", first_frame)
        return first_frame
    return os.fspath(first_frame)


async def _mark_clip_failed(factory, clip_id: str) -> None:
    async with factory() as session:
        clip = await session.get(Clip, clip_id)
        if clip is None:
            return
        clip.status = "failed"
        await session.commit()


async def _load_existing_first_frame(factory, clip_id: str) -> str | None:
    """改 30%：从 frame_assets 取该 clip 的原首帧 url，保持单段重生成时画面连续。

    选最新一条（按 created_at desc）。若没有，返回 None 让上游决定 fallback 策略。
    """
    async with factory() as session:
        result = await session.execute(
            select(FrameAsset)
            .where(FrameAsset.clip_id == clip_id, FrameAsset.kind == "first")
            .order_by(FrameAsset.created_at.desc())
        )
        frames = result.scalars().all()
        if not frames:
            return None
        return _resolve_first_frame_path(frames[0].url)


def _estimate_clip_cost(duration_sec: int) -> float:
    settings = get_settings()
    return settings.kling_cost_10s if duration_sec >= 10 else settings.kling_cost_5s
