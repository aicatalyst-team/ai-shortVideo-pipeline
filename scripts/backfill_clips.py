"""M3 backfill: extract clips from plans.evaluation JSONB into v2 tables.

Run once in the orchestrator container:
    python scripts/backfill_clips.py

The script is idempotent:
- plans with an existing storyboards.plan_id are skipped
- --force deletes the old storyboard first, then rebuilds it
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Make direct docker exec runs work even when PYTHONPATH is not set.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select, text

from db.connection import get_engine, get_session_factory
from db.models import Clip, Plan, Storyboard, _short_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("backfill_clips")

ALEMBIC_HEAD = "004"


async def _check_alembic_at_head() -> bool:
    """Return True when alembic_version is exactly the expected D24 head."""
    engine = get_engine()
    async with engine.connect() as conn:
        try:
            result = await conn.execute(text("select version_num from alembic_version"))
            row = result.fetchone()
        except Exception as e:
            log.error("alembic_version table missing or unreadable: %s", e)
            return False

    if not row:
        log.error("alembic_version is empty; alembic has not been initialized")
        return False

    current = row[0]
    if current != ALEMBIC_HEAD:
        log.error(
            "alembic_version=%s != head=%s. Run alembic upgrade head or stamp head first.",
            current,
            ALEMBIC_HEAD,
        )
        return False

    log.info("alembic_version=%s OK", current)
    return True


def _extract_top_ranked(evaluation: dict[str, Any] | None) -> dict[str, Any] | None:
    """Pick ranked[0], with scripts[0] as a compatibility alias."""
    if not evaluation or not isinstance(evaluation, dict):
        return None

    ranked = evaluation.get("ranked") or evaluation.get("scripts") or []
    if not ranked or not isinstance(ranked, list):
        return None

    first = ranked[0]
    return first if isinstance(first, dict) else None


def _build_storyboard_from_plan(plan: Plan, top: dict[str, Any]) -> Storyboard:
    """Build a Storyboard row from a legacy Plan and its top-ranked script."""
    theme = getattr(plan, "theme", "") or ""
    style_name = getattr(plan, "style_name", "") or "hot_news_commentary"
    title = (top.get("angle", "") or theme or "untitled")[:100]

    return Storyboard(
        id=_short_id(),
        plan_id=plan.id,
        title=title,
        theme=theme,
        style_name=style_name,
        status="ready",
        storyboard_metadata={
            "source": "backfill_from_plan_evaluation",
            "backfilled_at": datetime.utcnow().isoformat(),
            "original_score": top.get("score"),
            "original_angle": top.get("angle"),
            "original_hook": top.get("hook"),
            "original_tags": top.get("tags", []),
        },
    )


def _build_clips_from_scenes(storyboard_id: str, scenes: list[dict[str, Any]]) -> list[Clip]:
    """Build Clip rows from a legacy ranked[0].scenes array."""
    clips: list[Clip] = []
    for idx, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            continue

        clips.append(
            Clip(
                id=_short_id(),
                storyboard_id=storyboard_id,
                seq=scene.get("scene_no", idx),
                prompt=scene.get("image_desc", ""),
                kling_prompt="",
                narration_segment=scene.get("narration_segment", ""),
                duration_sec=int(scene.get("duration_sec", 5)),
                video_url=scene.get("video_url", "") or scene.get("video_path", ""),
                status="ready",
                cost_cny=0.0,
                r_metadata={
                    "source": "backfill_from_plan_scene",
                    "original_scene": scene,
                },
            )
        )
    return clips


async def backfill_one_plan(plan: Plan, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
    """Backfill one Plan. Returns a small stats dict for reporting.

    加 dry_run 参数（只走流程不写库，方便运维预演）。
    """
    stats: dict[str, Any] = {"plan_id": plan.id, "skipped": False, "clips": 0, "reason": "", "dry_run": dry_run}

    top = _extract_top_ranked(plan.evaluation)
    if not top:
        stats["skipped"] = True
        stats["reason"] = "no evaluation.ranked"
        return stats

    scenes = top.get("scenes") or []
    if not scenes:
        stats["skipped"] = True
        stats["reason"] = "no scenes in top ranked"
        return stats

    async with get_session_factory()() as session:
        existing = await session.execute(select(Storyboard).where(Storyboard.plan_id == plan.id))
        existing_sb = existing.scalar_one_or_none()

        if existing_sb and not force:
            stats["skipped"] = True
            stats["reason"] = f"already backfilled (storyboard_id={existing_sb.id})"
            return stats

        if existing_sb and force:
            if dry_run:
                log.info("[DRY-RUN] would delete old storyboard %s", existing_sb.id)
            else:
                log.info("force=True, deleting old storyboard %s", existing_sb.id)
                await session.delete(existing_sb)
                await session.flush()

        sb = _build_storyboard_from_plan(plan, top)
        clips_preview = _build_clips_from_scenes(sb.id, scenes)

        if dry_run:
            log.info(
                "[DRY-RUN] would create storyboard %s for plan %s with %d clips (title=%r)",
                sb.id, plan.id, len(clips_preview), sb.title[:50],
            )
            for c in clips_preview[:3]:
                log.info("[DRY-RUN]   clip seq=%d narration=%r", c.seq, c.narration_segment[:60])
            if len(clips_preview) > 3:
                log.info("[DRY-RUN]   ... and %d more clips", len(clips_preview) - 3)
            stats["clips"] = len(clips_preview)
            stats["storyboard_id"] = sb.id
            stats["reason"] = "dry-run preview, no commit"
            return stats

        session.add(sb)
        await session.flush()
        for clip in clips_preview:
            clip.storyboard_id = sb.id  # 重新绑定（flush 后 id 才生效）
            session.add(clip)

        await session.commit()
        stats["clips"] = len(clips_preview)
        stats["storyboard_id"] = sb.id
        log.info("backfilled plan %s -> storyboard %s (%d clips)", plan.id, sb.id, len(clips_preview))

    return stats


async def backfill_all(
    force: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
    plan_id: str | None = None,
) -> dict[str, Any]:
    """Scan non-archived plans and backfill all eligible rows.

    加 dry_run + plan_id 参数。
    - dry_run: 只走流程不写库，预演用
    - plan_id: 只回灌指定 plan（运维定向修复用）
    """
    total_stats: dict[str, Any] = {
        "total_plans": 0,
        "backfilled": 0,
        "skipped": 0,
        "errored": 0,
        "total_clips": 0,
        "dry_run": dry_run,
        "plan_id_filter": plan_id,
        "details": [],
    }

    async with get_session_factory()() as session:
        query = select(Plan).where(Plan.archived.is_(False))
        if plan_id:
            # 单 plan 回灌（运维定向修复）
            query = query.where(Plan.id == plan_id)
        query = query.order_by(Plan.created_at)
        if limit:
            query = query.limit(limit)
        result = await session.execute(query)
        plans = result.scalars().all()

    total_stats["total_plans"] = len(plans)

    if plan_id and not plans:
        log.warning("plan_id=%s not found or archived; nothing to backfill", plan_id)
        return total_stats

    mode_tag = "[DRY-RUN] " if dry_run else ""
    log.info("%sstarting backfill for %d non-archived plans%s",
             mode_tag, len(plans), f" (filter: plan_id={plan_id})" if plan_id else "")

    for plan in plans:
        try:
            stats = await backfill_one_plan(plan, force=force, dry_run=dry_run)
        except Exception as e:
            log.exception("backfill failed for plan %s: %s", plan.id, e)
            total_stats["errored"] += 1
            total_stats["details"].append({"plan_id": plan.id, "error": str(e)[:200]})
            continue

        if stats.get("skipped"):
            total_stats["skipped"] += 1
        else:
            total_stats["backfilled"] += 1
            total_stats["total_clips"] += stats.get("clips", 0)
        total_stats["details"].append(stats)

    return total_stats


async def main_async(args: argparse.Namespace) -> int:
    if not args.skip_check:
        ok = await _check_alembic_at_head()
        if not ok:
            return 2

    stats = await backfill_all(
        force=args.force,
        limit=args.limit,
        dry_run=args.dry_run,
        plan_id=args.plan_id,
    )
    log.info("=" * 60)
    label = "DRY-RUN preview" if args.dry_run else "backfill complete"
    log.info("%s:", label)
    log.info("  total_plans = %d", stats["total_plans"])
    log.info("  backfilled  = %d", stats["backfilled"])
    log.info("  skipped     = %d", stats["skipped"])
    log.info("  errored     = %d", stats["errored"])
    log.info("  total_clips = %d", stats["total_clips"])
    if args.dry_run:
        log.info("  (no rows committed; rerun without --dry-run to persist)")

    if args.output:
        Path(args.output).write_text(
            json.dumps(stats, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        log.info("detail report written to %s", args.output)

    return 0 if stats["errored"] == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill plans.evaluation into v2 tables")
    parser.add_argument("--force", action="store_true", help="delete existing storyboards and rebuild")
    parser.add_argument("--limit", type=int, help="process only the first N plans")
    parser.add_argument("--skip-check", action="store_true", help="skip alembic_version check for CI")
    parser.add_argument("--output", type=str, help="write detailed JSON report")
    # 运维实战增强
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview only, do not write to DB (use this BEFORE first real run)",
    )
    parser.add_argument(
        "--plan-id",
        type=str,
        default=None,
        help="backfill only the specified plan (operator-targeted repair)",
    )
    args = parser.parse_args()

    exit_code = asyncio.run(main_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
