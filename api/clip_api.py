"""clip regeneration REST API plus polling job status."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from core.scheduler import enqueue_job
from db.connection import get_session_factory
from db.models import Clip as ClipORM
from db.models import Job as JobORM


# 活跃任务状态（用于并发预检）
ACTIVE_JOB_STATUSES = ("queued", "running")

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["clip"])


class RegenerateRequest(BaseModel):
    new_prompt: str | None = Field(default=None, max_length=2000)
    new_kling_prompt: str | None = Field(default=None, max_length=2000)
    new_first_frame_url: str | None = Field(default=None, max_length=500)


class RegenerateAcceptedResponse(BaseModel):
    job_id: str
    clip_id: str
    status: str = "queued"
    poll_url: str


class JobStatusResponse(BaseModel):
    job_id: str
    job_type: str
    status: str
    progress: int = 0
    progress_stage: str = ""
    result: dict | None = None
    error: str | None = None


@router.post(
    "/clips/{clip_id}/regenerate",
    response_model=RegenerateAcceptedResponse,
    status_code=202,
)
async def regenerate_clip_endpoint(
    clip_id: str,
    body: RegenerateRequest,
) -> RegenerateAcceptedResponse:
    """Queue a single-clip regeneration job and return a pollable job_id."""
    if (
        body.new_prompt is None
        and body.new_kling_prompt is None
        and body.new_first_frame_url is None
    ):
        raise HTTPException(
            status_code=400,
            detail="at least one of new_prompt / new_kling_prompt / new_first_frame_url required",
        )

    async with get_session_factory()() as session:
        clip = await session.get(ClipORM, clip_id)
        if clip is None:
            raise HTTPException(status_code=404, detail=f"clip {clip_id} not found")

        # 并发保护
        # 防止同 clip 短时间多次 POST 入队 → 多 worker 并发跑同 clip → race condition
        active_q = await session.execute(
            select(JobORM)
            .where(
                JobORM.target_id == clip_id,
                JobORM.status.in_(ACTIVE_JOB_STATUSES),
            )
            .order_by(JobORM.created_at.desc())
            .limit(1)
        )
        active_job = active_q.scalar_one_or_none()
        if active_job is not None:
            log.warning(
                "[clip_api] reject duplicate regenerate clip=%s; existing job=%s status=%s",
                clip_id, active_job.id, active_job.status,
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "regenerate_already_running",
                    "message": f"clip {clip_id} already has an active regenerate job",
                    "existing_job_id": active_job.id,
                    "existing_status": active_job.status,
                    "existing_progress": active_job.progress,
                    "existing_poll_url": f"/api/v1/jobs/{active_job.id}",
                },
            )

    job_id = await enqueue_job(
        "task_regenerate_clip",
        clip_id,
        body.new_prompt,
        body.new_kling_prompt,
        body.new_first_frame_url,
    )

    async with get_session_factory()() as session:
        session.add(
            JobORM(
                id=job_id,
                job_type="regenerate_clip",
                status="queued",
                progress=0,
                progress_stage="queued",
                target_id=clip_id,  # 改 30%: 写入便于活跃任务反查
            )
        )
        await session.commit()

    log.info("[clip_api] regenerate enqueued clip=%s job=%s", clip_id, job_id)

    return RegenerateAcceptedResponse(
        job_id=job_id,
        clip_id=clip_id,
        status="queued",
        poll_url=f"/api/v1/jobs/{job_id}",
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str) -> JobStatusResponse:
    """Read the current job status and progress from jobs table."""
    async with get_session_factory()() as session:
        job = await session.get(JobORM, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"job {job_id} not found")

        return JobStatusResponse(
            job_id=job.id,
            job_type=job.job_type,
            status=job.status,
            progress=job.progress,
            progress_stage=job.progress_stage,
            result=job.result,
            error=job.error,
        )
