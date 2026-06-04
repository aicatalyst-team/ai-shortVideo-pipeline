"""Phase P Sprint P11: Kling 3.0 vs stitched_i2v A/B comparison script.

Usage:
  python scripts/run_kling3_ab_compare.py ^
      --theme "Google I/O" ^
      --narration "AI coding is becoming the default production interface" ^
      --rounds 3 ^
      --output_dir output/poc_kling3_20260525
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


async def run_stitched_round(theme: str, narration: str, output_path: Path) -> dict[str, Any]:
    """Run a simplified stitched_i2v round for generation-speed comparison only."""
    from layers.L2_creative.style_engine import get_template
    from layers.L3_visual.image_to_video import generate_clip

    style = get_template("hot_news_commentary")
    started = time.time()
    error = ""
    duration_sec = 0.0
    try:
        result = await generate_clip(
            image_prompt=f"{theme}, news editorial style, high contrast",
            kling_prompt=f"camera slow push in, {theme}",
            output_path=str(output_path),
            style=style,
            duration_sec=5,
            quality="standard",
        )
        duration_sec = float(result.duration_sec or 0)
    except Exception as exc:
        error = str(exc)[:300]
        log.error("[stitched] failed: %s", exc)
    return {
        "mode": "stitched_i2v",
        "elapsed_sec": round(time.time() - started, 2),
        "duration_sec": duration_sec,
        "audio_included": False,
        "error": error,
        "output_path": str(output_path),
        "narration_chars": len((narration or "").strip()),
    }


async def run_kling3_round(theme: str, narration: str, output_path: Path) -> dict[str, Any]:
    """Run one Kling 3.0 native-audio round."""
    from layers.L3_visual.providers.kling3 import (
        Kling3FeatureUnsupportedError,
        Kling3NotAvailableError,
        Kling3Request,
        generate_native_audio_video,
    )

    request = Kling3Request(
        image_path=None,
        narration=narration,
        visual_prompt=f"{theme}, news editorial style, high contrast",
        duration_sec=5,
        enable_native_audio=True,
    )
    started = time.time()
    error = ""
    duration_sec = 0.0
    audio_included = False
    try:
        result = await generate_native_audio_video(request, output_path=str(output_path))
        duration_sec = float(result.actual_duration_sec)
        audio_included = result.audio_included
    except Kling3NotAvailableError as exc:
        error = f"NOT_AVAILABLE: {exc}"
        log.error("[kling3] not available: %s", exc)
    except Kling3FeatureUnsupportedError as exc:
        error = f"FEATURE_UNSUPPORTED: {exc}"
        log.error("[kling3] feature unsupported: %s", exc)
    except Exception as exc:
        error = f"OTHER: {exc}"
        log.error("[kling3] failed: %s", exc)
    return {
        "mode": "kling3_native_audio",
        "elapsed_sec": round(time.time() - started, 2),
        "duration_sec": duration_sec,
        "audio_included": audio_included,
        "error": error,
        "output_path": str(output_path),
        "narration_chars": len((narration or "").strip()),
    }


def write_markdown_report(report: list[dict], out_path: Path) -> None:
    """Render the JSON report into a compact Markdown table."""
    rows = [
        "| Round | Mode | Elapsed (s) | Duration (s) | Audio? | Error |",
        "|---|---|---|---|---|---|",
    ]
    for row in report:
        err = (row["error"] or "")[:60].replace("\n", " ")
        rows.append(
            f"| {row['round']} | {row['mode']} | {row['elapsed_sec']:.1f} | "
            f"{row['duration_sec']:.1f} | {'yes' if row['audio_included'] else 'no'} | {err or '-'} |"
        )
    out_path.write_text("\n".join(rows) + "\n", encoding="utf-8")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", required=True)
    parser.add_argument("--narration", required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output_dir", required=True)
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    (out_dir / "stitched").mkdir(parents=True, exist_ok=True)
    (out_dir / "kling3").mkdir(parents=True, exist_ok=True)

    report: list[dict[str, Any]] = []
    for round_no in range(1, args.rounds + 1):
        log.info("=" * 50)
        log.info("Round %d / %d", round_no, args.rounds)

        stitched = await run_stitched_round(
            args.theme,
            args.narration,
            out_dir / "stitched" / f"round_{round_no}.mp4",
        )
        stitched["round"] = round_no
        report.append(stitched)

        kling3 = await run_kling3_round(
            args.theme,
            args.narration,
            out_dir / "kling3" / f"round_{round_no}.mp4",
        )
        kling3["round"] = round_no
        report.append(kling3)

    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_markdown_report(report, out_dir / "report.md")
    log.info("Report written to %s", out_dir)


if __name__ == "__main__":
    asyncio.run(main())
