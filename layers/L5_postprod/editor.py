"""视频后期编辑模块

FFmpeg 工具集：拼接、压缩（多档位）、抽帧、裁剪。
从 pipeline/video_pipeline.py 重构而来。
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

CompressPreset = Literal["preview", "douyin", "bilibili", "hd"]

_COMPRESS_PRESETS: dict[str, dict] = {
    "preview": {
        "crf": 32,
        "scale": "480:-2",
        "audio_bitrate": "64k",
        "desc": "预览级，小文件快速查看",
    },
    "douyin": {
        "crf": 23,
        "scale": "1080:-2",
        "audio_bitrate": "128k",
        "desc": "抖音/小红书竖屏，1080p，<50MB",
    },
    "bilibili": {
        "crf": 20,
        "scale": "1080:-2",
        "audio_bitrate": "192k",
        "desc": "B站高画质，1080p",
    },
    "hd": {
        "crf": 18,
        "scale": "1920:-2",
        "audio_bitrate": "256k",
        "desc": "高清存档，接近无损",
    },
}


async def compress(
    input_path: Path | str,
    output_path: Path | str,
    preset: CompressPreset = "douyin",
) -> Path:
    """按预设压缩视频"""
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    params = _COMPRESS_PRESETS[preset]

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vcodec", "libx264",
        "-crf", str(params["crf"]),
        "-vf", f"scale={params['scale']}",
        "-acodec", "aac",
        "-b:a", params["audio_bitrate"],
        "-movflags", "+faststart",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"Compress failed: {stderr.decode()[-300:]}")

    size_mb = output_path.stat().st_size / 1024 / 1024
    logger.info("Compressed [%s]: %s -> %.1fMB", preset, output_path.name, size_mb)
    return output_path


async def concat_clips(
    clip_paths: list[str | Path],
    output_path: Path | str,
) -> Path:
    """FFmpeg concat 拼接多个片段"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    list_content = "\n".join(f"file '{Path(p).resolve()}'" for p in clip_paths)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(list_content)
        list_file = f.name

    try:
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            str(output_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Concat failed: {stderr.decode()[-300:]}")
    finally:
        os.unlink(list_file)

    logger.info("Concat %d clips -> %s", len(clip_paths), output_path)
    return output_path


async def extract_frames(
    video_path: Path | str,
    output_dir: Path | str,
    fps: int = 1,
    max_sec: int = 30,
) -> list[Path]:
    """提取关键帧（JPEG，720p 以内）"""
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    out_pattern = str(output_dir / "frame_%03d.jpg")

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", f"fps={fps},scale=720:-2",
        "-t", str(max_sec),
        out_pattern,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()

    frames = sorted(output_dir.glob("frame_*.jpg"))
    logger.info("Extracted %d frames from %s", len(frames), video_path.name)
    return frames


async def extract_last_frame(
    video_path: Path | str,
    output_path: Path | str,
) -> Path:
    """提取视频最后一帧"""
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-sseof", "-0.04",
        "-i", str(video_path),
        "-update", "1",
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"Extract last frame failed: {output_path}")

    return output_path


async def trim(
    video_path: Path | str,
    output_path: Path | str,
    start_sec: float = 0,
    duration_sec: float | None = None,
    end_sec: float | None = None,
) -> Path:
    """裁剪视频片段"""
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_sec),
        "-i", str(video_path),
    ]

    if duration_sec is not None:
        cmd.extend(["-t", str(duration_sec)])
    elif end_sec is not None:
        cmd.extend(["-t", str(end_sec - start_sec)])

    cmd.extend(["-c", "copy", str(output_path)])

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"Trim failed: {stderr.decode()[-300:]}")

    return output_path


async def apply_film_grain(
    input_path: Path | str,
    output_path: Path | str,
    grain_strength: int = 18,
) -> Path:
    """胶片质感后处理：noise + 曲线压暗 + 暗角（修复硬伤4：AI 感过重）

    grain_strength: 噪点强度，推荐 12-25，过高会掉画质
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # noise=颗粒感 / eq=对比微调+轻微降饱 / vignette=暗角
    vf = (
        f"noise=alls={grain_strength}:allf=t+u,"
        f"eq=contrast=1.04:saturation=0.88:brightness=-0.02,"
        f"vignette=angle=PI/5:mode=forward"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", vf,
        "-c:v", "libx264", "-crf", "20",
        "-c:a", "copy",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"Film grain failed: {stderr.decode()[-300:]}")

    logger.info("Film grain applied [strength=%d]: %s", grain_strength, output_path.name)
    return output_path


def list_presets() -> list[dict]:
    """查看所有压缩预设"""
    return [
        {"preset": k, **v}
        for k, v in _COMPRESS_PRESETS.items()
    ]
