"""Storyboard read-only API.

W3 D16 used an in-memory store for v2 Storyboard objects. D24 upgrades reads to
prefer PostgreSQL v2 tables, while keeping the in-memory path as a compatibility
fallback until chains_v2 writes directly to PG.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from db.connection import get_session_factory
from db.models import Clip as ClipORM
from db.models import FrameAsset as FrameAssetORM
from db.models import Storyboard as StoryboardORM
from layers.L2_creative.canvas_node_service import (
    ClipNodeData,
    CostSummary,
    build_clip_node_data,
    build_cost_summary,
)
from layers.L2_creative.schemas import Storyboard
from layers.L2_creative.storyboard_engine import generate_storyboard_thumbnails

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/storyboards", tags=["storyboard"])

_STORYBOARD_STORE: dict[str, Storyboard] = {}


def register_storyboard(storyboard: Storyboard) -> None:
    """Register a v2 Storyboard in memory during the compatibility window."""
    _STORYBOARD_STORE[storyboard.plan_id] = storyboard
    log.info("[storyboard_api] in-memory registered plan_id=%s", storyboard.plan_id)


class ClipResponse(BaseModel):
    id: str
    seq: int
    prompt: str
    narration_segment: str
    duration_sec: int
    video_url: str
    status: str
    r_metadata: dict | None = None


class FrameAssetResponse(BaseModel):
    id: str
    clip_id: str | None
    kind: str
    url: str
    width: int
    height: int


class StoryboardDbResponse(BaseModel):
    """Storyboard read from PG, including clips and optional frame assets."""

    id: str
    plan_id: str | None
    title: str
    theme: str
    style_name: str
    status: str
    metadata: dict | None
    clips: list[ClipResponse]
    frames: list[FrameAssetResponse] = []
    source: str = "db"
    # Phase P P10 新增：画布节点完整 7 类数据 + 整 storyboard 成本汇总
    clip_nodes: list[ClipNodeData] = []
    cost_summary: CostSummary | None = None


class ThumbnailItemResponse(BaseModel):
    scene_no: int
    success: bool
    image_url: str = ""
    prompt_used: str = ""
    error: str = ""
    duration_ms: int = 0


class StoryboardPreviewResponse(BaseModel):
    plan_id: str
    title: str
    total_shots: int
    succeeded: int
    failed: int
    storyboard: dict
    thumbnails: list[ThumbnailItemResponse]


@router.get("/{plan_id}", response_model=StoryboardDbResponse)
async def get_storyboard(
    plan_id: str,
    include_frames: bool = Query(False, description="Return frame_assets as well"),
) -> StoryboardDbResponse:
    """Read a storyboard by plan_id. Prefer PG, fallback to in-memory."""
    async with get_session_factory()() as session:
        result = await session.execute(select(StoryboardORM).where(StoryboardORM.plan_id == plan_id))
        sb_orm = result.scalar_one_or_none()

        if sb_orm:
            clips_result = await session.execute(
                select(ClipORM).where(ClipORM.storyboard_id == sb_orm.id).order_by(ClipORM.seq)
            )
            clips = clips_result.scalars().all()

            frames = []
            if include_frames and clips:
                clip_ids = [c.id for c in clips]
                frames_result = await session.execute(
                    select(FrameAssetORM).where(FrameAssetORM.clip_id.in_(clip_ids))
                )
                frames = frames_result.scalars().all()

            # Phase P P10：构造 clip_nodes（7 类数据组）+ cost_summary
            frame_list = list(frames) if frames else []
            clip_nodes = [build_clip_node_data(c, frame_assets=frame_list) for c in clips]
            cost_summary = build_cost_summary(list(clips))

            return StoryboardDbResponse(
                id=sb_orm.id,
                plan_id=sb_orm.plan_id,
                title=sb_orm.title,
                theme=sb_orm.theme,
                style_name=sb_orm.style_name,
                status=sb_orm.status,
                metadata=sb_orm.storyboard_metadata,
                clips=[
                    ClipResponse(
                        id=c.id,
                        seq=c.seq,
                        prompt=c.prompt,
                        narration_segment=c.narration_segment,
                        duration_sec=c.duration_sec,
                        video_url=c.video_url,
                        status=c.status,
                        r_metadata=c.r_metadata,
                    )
                    for c in clips
                ],
                frames=[
                    FrameAssetResponse(
                        id=f.id,
                        clip_id=f.clip_id,
                        kind=f.kind,
                        url=f.url,
                        width=f.width,
                        height=f.height,
                    )
                    for f in frames
                ],
                clip_nodes=clip_nodes,
                cost_summary=cost_summary,
                source="db",
            )

    in_mem = _STORYBOARD_STORE.get(plan_id)
    if in_mem:
        return StoryboardDbResponse(
            id=f"mem_{plan_id}",
            plan_id=in_mem.plan_id,
            title=in_mem.title,
            theme=in_mem.theme,
            style_name=in_mem.style_name,
            status="in_memory",
            metadata={"source": "in_memory"},
            clips=[
                ClipResponse(
                    id=f"mem_{shot.scene_no}",
                    seq=shot.scene_no,
                    prompt="",
                    narration_segment=shot.narration_segment,
                    duration_sec=int(shot.estimated_duration_sec),
                    video_url="",
                    status="pending",
                    r_metadata=shot.model_dump(),
                )
                for shot in in_mem.shots
            ],
            source="in-memory",
        )

    raise HTTPException(status_code=404, detail=f"storyboard for plan_id={plan_id} not found")


@router.post("/{plan_id}/preview", response_model=StoryboardPreviewResponse)
async def preview_storyboard(plan_id: str) -> StoryboardPreviewResponse:
    """Generate preview thumbnails for in-memory storyboards.

    DB-backed preview waits for the D28 PG write/read integration.
    """
    sb = _STORYBOARD_STORE.get(plan_id)
    if not sb:
        raise HTTPException(
            status_code=404,
            detail=(
                f"in-memory storyboard {plan_id} not found "
                "(preview currently only supports in-memory storyboards)"
            ),
        )

    batch = await generate_storyboard_thumbnails(sb)
    items = [
        ThumbnailItemResponse(
            scene_no=r.scene_no,
            success=r.success,
            image_url=(r.image.url if r.image else "") if r.success else "",
            prompt_used=r.prompt_used,
            error=r.error,
            duration_ms=r.duration_ms,
        )
        for r in batch.items
    ]

    return StoryboardPreviewResponse(
        plan_id=sb.plan_id,
        title=sb.title,
        total_shots=batch.total,
        succeeded=batch.succeeded,
        failed=batch.failed,
        storyboard=sb.model_dump(),
        thumbnails=items,
    )
