"""多比例适配模块

将视频转换为不同宽高比版本：9:16（竖屏）、1:1（方屏）、16:9（横屏）。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

Ratio = Literal["9:16", "1:1", "16:9"]

_RATIO_CONFIG: dict[str, dict] = {
    "9:16": {
        "width": 1080, "height": 1920,
        "scale": "1080:-2",
        "pad": "1080:1920:(ow-iw)/2:(oh-ih)/2:black",
        "crop": None,
    },
    "1:1": {
        "width": 1080, "height": 1080,
        "scale": None,
        "pad": None,
        "crop": "min(iw\\,ih):min(iw\\,ih):(iw-min(iw\\,ih))/2:(ih-min(iw\\,ih))/2",
    },
    "16:9": {
        "width": 1920, "height": 1080,
        "scale": None,
        "pad": None,
        "crop": "iw:iw*9/16:0:(ih-iw*9/16)/2",
    },
}


@dataclass
class RatioResult:
    ratio: str
    file_path: Path
    width: int
    height: int


def _build_vf(source_ratio: str, target_ratio: str) -> str:
    """构建视频滤镜表达式"""
    cfg = _RATIO_CONFIG[target_ratio]

    if source_ratio == target_ratio:
        return ""

    if source_ratio == "9:16":
        if target_ratio == "1:1":
            return (
                "crop=iw:iw:0:(ih-iw)/2,"
                "scale=1080:1080"
            )
        if target_ratio == "16:9":
            return (
                "split[bg][fg];"
                "[bg]scale=1920:1080,boxblur=20:20[blur];"
                "[fg]scale=-2:1080[main];"
                "[blur][main]overlay=(W-w)/2:0"
            )

    if source_ratio == "16:9":
        if target_ratio == "9:16":
            return (
                "split[bg][fg];"
                "[bg]scale=1080:1920,boxblur=20:20[blur];"
                "[fg]scale=1080:-2[main];"
                "[blur][main]overlay=0:(H-h)/2"
            )
        if target_ratio == "1:1":
            return (
                "crop=ih:ih:(iw-ih)/2:0,"
                "scale=1080:1080"
            )

    if cfg["crop"]:
        vf = f"crop={cfg['crop']},scale={cfg['width']}:{cfg['height']}"
    else:
        vf = f"scale={cfg['scale']}"
        if cfg["pad"]:
            vf += f",pad={cfg['pad']}"

    return vf


def _detect_ratio(width: int, height: int) -> str:
    """检测视频原始比例"""
    r = width / height
    if r < 0.7:
        return "9:16"
    elif r > 1.4:
        return "16:9"
    else:
        return "1:1"


def _get_video_dimensions(video_path: Path) -> tuple[int, int]:
    import subprocess
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0:s=x",
            "-select_streams", "v:0",
            str(video_path),
        ],
        capture_output=True, text=True,
    )
    parts = result.stdout.strip().split("x")
    if len(parts) == 2:
        return int(parts[0]), int(parts[1])
    return 1080, 1920


async def convert_ratio(
    video_path: Path | str,
    output_path: Path | str,
    target_ratio: Ratio = "1:1",
) -> RatioResult:
    """将视频转换为目标比例"""
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    w, h = _get_video_dimensions(video_path)
    source_ratio = _detect_ratio(w, h)
    cfg = _RATIO_CONFIG[target_ratio]

    vf = _build_vf(source_ratio, target_ratio)

    if not vf:
        import shutil
        shutil.copy2(video_path, output_path)
        return RatioResult(ratio=target_ratio, file_path=output_path,
                           width=cfg["width"], height=cfg["height"])

    if "split" in vf:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-filter_complex", vf,
            "-c:a", "copy",
            str(output_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", vf,
            "-c:a", "copy",
            str(output_path),
        ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"Ratio convert failed: {stderr.decode()[-300:]}")

    logger.info("Converted %s -> %s: %s", source_ratio, target_ratio, output_path)
    return RatioResult(
        ratio=target_ratio, file_path=output_path,
        width=cfg["width"], height=cfg["height"],
    )


async def generate_all_ratios(
    video_path: Path | str,
    output_dir: Path | str,
    filename_prefix: str = "video",
) -> list[RatioResult]:
    """生成全部 3 种比例版本"""
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ratios: list[Ratio] = ["9:16", "1:1", "16:9"]
    ratio_names = {"9:16": "vertical", "1:1": "square", "16:9": "horizontal"}

    results = []
    for ratio in ratios:
        name = ratio_names[ratio]
        out = output_dir / f"{filename_prefix}_{name}.mp4"
        result = await convert_ratio(video_path, out, ratio)
        results.append(result)

    logger.info("Generated %d ratio variants in %s", len(results), output_dir)
    return results
