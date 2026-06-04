""" demo: run v1 and v2 creative flows for the same theme.

Usage:
    python scripts/run_phase_r_demo.py --theme "咖啡涨价" --character su_wan --style hot_news_commentary

Artifacts:
    demo/phase_r/<timestamp>_<theme>/v1_output.json
    demo/phase_r/<timestamp>_<theme>/v2_storyboard.json
    demo/phase_r/<timestamp>_<theme>/v2_score_report.json
    demo/phase_r/<timestamp>_<theme>/comparison.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from layers.L2_creative.chains import lobster_creative as lobster_creative_v1
from layers.L2_creative.chains_v2 import lobster_creative_v2, lobster_evaluate_v2
from layers.L2_creative.style_engine import get_template

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("phase_r_demo")


async def run_demo(theme: str, character: str, style_name: str) -> Path:
    style = get_template(style_name)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_theme = theme.replace("/", "_").replace("\\", "_").replace(" ", "_")[:30]
    out_dir = Path("demo/phase_r") / f"{timestamp}_{safe_theme}"
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info("[v1] running lobster_creative")
    try:
        v1_raw = await lobster_creative_v1(theme, style)
        (out_dir / "v1_output.json").write_text(v1_raw, encoding="utf-8")
        log.info("[v1] done, output length=%d", len(v1_raw))
    except Exception as e:
        log.error("[v1] failed: %s", e)
        (out_dir / "v1_error.txt").write_text(str(e), encoding="utf-8")

    log.info("[v2] running lobster_creative_v2")
    try:
        storyboard = await lobster_creative_v2(theme, style, main_character_id=character)
        (out_dir / "v2_storyboard.json").write_text(
            storyboard.model_dump_json(indent=2),
            encoding="utf-8",
        )
        log.info("[v2] done, shots=%d", len(storyboard.shots))

        log.info("[v2] running lobster_evaluate_v2")
        report = await lobster_evaluate_v2(storyboard)
        (out_dir / "v2_score_report.json").write_text(
            report.model_dump_json(indent=2),
            encoding="utf-8",
        )
        log.info("[v2] score=%.1f verdict=%s", report.overall_score, report.verdict)
    except Exception as e:
        log.error("[v2] failed: %s", e)
        (out_dir / "v2_error.txt").write_text(str(e), encoding="utf-8")

    comparison = _build_comparison_md(theme, character, style_name, out_dir)
    (out_dir / "comparison.md").write_text(comparison, encoding="utf-8")

    log.info("[demo] artifacts: %s", out_dir)
    return out_dir


def _build_comparison_md(theme: str, character: str, style: str, out_dir: Path) -> str:
    v1_path = out_dir / "v1_output.json"
    v2_path = out_dir / "v2_storyboard.json"
    score_path = out_dir / "v2_score_report.json"

    md = "# 对比演示\n\n"
    md += f"- 主题：{theme}\n- 主角：{character}\n- 风格：{style}\n- 时间：{datetime.now().isoformat()}\n\n"

    md += "## V1（旧流程）\n\n"
    if v1_path.exists():
        v1_text = v1_path.read_text(encoding="utf-8")
        md += f"- 输出长度：{len(v1_text)} 字\n"
        md += "- 文件：v1_output.json\n"
        md += "- 特征：自由文本 JSON，无 schema 校验，字段可能缺失/瞎写\n\n"
    else:
        md += "- 失败，见 v1_error.txt\n\n"

    md += "## V2（ 强 schema）\n\n"
    if v2_path.exists():
        sb = json.loads(v2_path.read_text(encoding="utf-8"))
        md += f"- shots 数：{len(sb['shots'])}\n"
        md += f"- 总时长：{sb['total_duration_sec']}s\n"
        md += f"- 主角：{sb['main_character_id']}\n"
        md += "- 特征：Pydantic 强 schema，字段类型 + 枚举 + 连续性全校验\n\n"

        if score_path.exists():
            report = json.loads(score_path.read_text(encoding="utf-8"))
            md += "### 五维评分（V2）\n\n"
            md += f"- **总分**：{report['overall_score']:.1f} / 100\n"
            md += f"- **裁决**：{report['verdict']}\n\n"
            md += "| 维度 | 分数 | 原因 |\n|---|---|---|\n"
            for d in report["dimension_scores"]:
                md += f"| {d['dimension']} | {d['score']} | {d['reason'][:60]}... |\n"
    else:
        md += "- 失败，见 v2_error.txt\n\n"

    return md


def main():
    parser = argparse.ArgumentParser(description=" demo")
    parser.add_argument("--theme", required=True)
    parser.add_argument(
        "--character",
        default="su_wan",
        choices=["su_wan", "lin_yue", "chen_xing", "ye_cheng"],
    )
    parser.add_argument("--style", default="hot_news_commentary")
    args = parser.parse_args()

    asyncio.run(run_demo(args.theme, args.character, args.style))


if __name__ == "__main__":
    main()
