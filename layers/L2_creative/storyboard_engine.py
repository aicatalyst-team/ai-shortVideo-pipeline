"""3: storyboard preview thumbnails."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from config.settings import get_settings
from layers.L2_creative.character_manager import get_character
from layers.L2_creative.environment_manager import get_environment
from layers.L2_creative.schemas import SceneShot, Storyboard
from layers.L3_visual.providers.base import ImageResult

log = logging.getLogger(__name__)


@dataclass
class ThumbnailResult:
    scene_no: int
    success: bool
    image: ImageResult | None = None
    prompt_used: str = ""
    error: str = ""
    duration_ms: int = 0


@dataclass
class ThumbnailBatchResult:
    plan_id: str
    total: int
    succeeded: int
    failed: int
    items: list[ThumbnailResult] = field(default_factory=list)


def _build_thumbnail_prompt(shot: SceneShot) -> str:
    """Build a lightweight preview prompt for fast storyboard thumbnails."""
    character = get_character(shot.character_id)
    env = get_environment(shot.environment_id)

    char_desc = character.visual_tags or character.display_name if character else shot.character_id
    env_desc = env.display_name if env else shot.environment_id

    return (
        f"{char_desc}, {shot.subject_action}, "
        f"emotion: {shot.subject_emotion}, "
        f"at {env_desc} {shot.time_of_day}, "
        f"{shot.position.camera_distance} shot, {shot.position.camera_angle} angle, "
        f"{shot.lighting_mood} lighting, {shot.composition} composition, "
        "draft thumbnail quality"
    )


async def _generate_one_thumbnail(
    shot: SceneShot,
    output_dir: Path,
    timeout_sec: int = 60,
) -> ThumbnailResult:
    """Generate one thumbnail and convert failures into result objects."""
    from layers.L3_visual.text_to_image import generate_image
    from layers.L2_creative.prompt_builder import build_negative_prompt

    start = time.time()
    prompt = _build_thumbnail_prompt(shot)
    # R5 改 30% : 缩略图也接入 negative_prompt
    # 即使是 draft 阶段，加 negative 也能避免大量明显劣质图浪费 API 配额
    negative = build_negative_prompt(shot)
    out_path = output_dir / f"thumb_scene_{shot.scene_no:02d}.png"

    try:
        character = get_character(shot.character_id)
        ref_path = None
        if character:
            ref = character.front_ref_path()
            if ref and ref.exists():
                ref_path = str(ref)

        image = await asyncio.wait_for(
            generate_image(
                prompt=prompt,
                output_path=str(out_path),
                negative_prompt=negative,
                aspect_ratio="9:16",
                character_ref_path=ref_path,
            ),
            timeout=timeout_sec,
        )
        elapsed = int((time.time() - start) * 1000)
        log.info("[thumb] scene_no=%d success in %dms", shot.scene_no, elapsed)
        return ThumbnailResult(
            scene_no=shot.scene_no,
            success=True,
            image=image,
            prompt_used=prompt,
            duration_ms=elapsed,
        )
    except asyncio.TimeoutError:
        elapsed = int((time.time() - start) * 1000)
        log.warning("[thumb] scene_no=%d timeout after %dms", shot.scene_no, elapsed)
        return ThumbnailResult(
            scene_no=shot.scene_no,
            success=False,
            prompt_used=prompt,
            error=f"timeout after {timeout_sec}s",
            duration_ms=elapsed,
        )
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        log.error("[thumb] scene_no=%d failed: %s", shot.scene_no, e)
        return ThumbnailResult(
            scene_no=shot.scene_no,
            success=False,
            prompt_used=prompt,
            error=str(e)[:300],
            duration_ms=elapsed,
        )


async def generate_storyboard_thumbnails(
    storyboard: Storyboard,
    output_dir: Path | None = None,
    timeout_per_shot: int = 60,
    max_concurrency: int = 3,
) -> ThumbnailBatchResult:
    """Generate preview thumbnails for all shots with bounded concurrency."""
    cfg = get_settings()
    if output_dir is None:
        output_dir = cfg.output_dir / "thumbnails" / storyboard.plan_id
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info(
        "[thumb_batch] plan_id=%s shots=%d concurrency=%d",
        storyboard.plan_id,
        len(storyboard.shots),
        max_concurrency,
    )

    semaphore = asyncio.Semaphore(max_concurrency)

    async def _bounded(shot: SceneShot) -> ThumbnailResult:
        async with semaphore:
            return await _generate_one_thumbnail(shot, output_dir, timeout_per_shot)

    results = await asyncio.gather(*[_bounded(s) for s in storyboard.shots], return_exceptions=False)
    succeeded = sum(1 for r in results if r.success)
    log.info("[thumb_batch] done plan_id=%s succeeded=%d/%d", storyboard.plan_id, succeeded, len(results))

    return ThumbnailBatchResult(
        plan_id=storyboard.plan_id,
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        items=sorted(results, key=lambda r: r.scene_no),
    )
