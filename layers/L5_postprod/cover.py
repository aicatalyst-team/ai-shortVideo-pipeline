"""封面自动生成模块

从视频中提取关键帧，用 FFmpeg 叠加标题文字生成封面图。
支持自定义文字样式和布局。
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

CoverLayout = Literal["top", "center", "bottom", "top_left"]

_FONT_WIN = "C\\:/Windows/Fonts/msyhbd.ttc"
_FONT_LINUX = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"


@dataclass
class CoverConfig:
    title: str
    subtitle: str = ""
    layout: CoverLayout = "center"
    font_size_title: int = 64
    font_size_subtitle: int = 36
    title_color: str = "white"
    border_color: str = "black"
    border_width: int = 4
    overlay_opacity: float = 0.4


def _detect_font() -> str:
    if Path("C:/Windows/Fonts/msyhbd.ttc").exists():
        return _FONT_WIN
    return _FONT_LINUX


async def extract_best_frame(
    video_path: Path | str,
    output_path: Path | str,
    timestamp_sec: float = 1.0,
) -> Path:
    """从视频指定时间点提取一帧作为封面底图"""
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp_sec),
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"Frame extraction failed: {stderr.decode()[-200:]}")

    return output_path


def _build_cover_filter(config: CoverConfig, width: int = 1080, height: int = 1920) -> str:
    """构建封面叠加滤镜"""
    font = _detect_font()
    filters = []

    opacity = config.overlay_opacity
    if opacity > 0:
        filters.append(
            f"drawbox=x=0:y=0:w={width}:h={height}:"
            f"color=black@{opacity}:t=fill"
        )

    title_safe = config.title.replace("'", "\\'").replace(":", "\\:")
    layout = config.layout

    if layout == "top":
        title_y, sub_y = "100", "180"
    elif layout == "bottom":
        title_y, sub_y = f"{height - 250}", f"{height - 170}"
    elif layout == "top_left":
        title_y, sub_y = "100", "180"
    else:
        title_y = f"({height}-text_h)/2-30"
        sub_y = f"({height}+text_h)/2+20"

    title_x = "50" if layout == "top_left" else "(w-text_w)/2"

    filters.append(
        f"drawtext=text='{title_safe}':"
        f"fontfile={font}:"
        f"fontsize={config.font_size_title}:"
        f"fontcolor={config.title_color}:"
        f"bordercolor={config.border_color}:"
        f"borderw={config.border_width}:"
        f"x={title_x}:y={title_y}"
    )

    if config.subtitle:
        sub_safe = config.subtitle.replace("'", "\\'").replace(":", "\\:")
        sub_x = "50" if layout == "top_left" else "(w-text_w)/2"
        filters.append(
            f"drawtext=text='{sub_safe}':"
            f"fontfile={font}:"
            f"fontsize={config.font_size_subtitle}:"
            f"fontcolor={config.title_color}@0.8:"
            f"bordercolor={config.border_color}:"
            f"borderw=2:"
            f"x={sub_x}:y={sub_y}"
        )

    return ",".join(filters)


async def generate_cover(
    video_path: Path | str,
    output_path: Path | str,
    title: str,
    subtitle: str = "",
    layout: CoverLayout = "center",
    frame_sec: float = 1.0,
    overlay_opacity: float = 0.4,
) -> Path:
    """从视频生成封面图：提取帧 + 叠加标题

    Args:
        video_path: 源视频
        output_path: 输出封面图(.jpg/.png)
        title: 主标题
        subtitle: 副标题
        layout: 文字布局位置
        frame_sec: 截取哪一秒的帧
        overlay_opacity: 暗色蒙层透明度 (0=无蒙层)
    """
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    config = CoverConfig(
        title=title,
        subtitle=subtitle,
        layout=layout,
        overlay_opacity=overlay_opacity,
    )
    vf = _build_cover_filter(config)

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(frame_sec),
        "-i", str(video_path),
        "-frames:v", "1",
        "-vf", vf,
        "-q:v", "2",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"Cover generation failed: {stderr.decode()[-300:]}")

    logger.info("Cover generated: %s [%s]", output_path, layout)
    return output_path


async def generate_cover_from_image(
    image_path: Path | str,
    output_path: Path | str,
    title: str,
    subtitle: str = "",
    layout: CoverLayout = "center",
    overlay_opacity: float = 0.4,
) -> Path:
    """从已有图片生成封面（叠加标题文字）"""
    image_path = Path(image_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    config = CoverConfig(
        title=title, subtitle=subtitle,
        layout=layout, overlay_opacity=overlay_opacity,
    )
    vf = _build_cover_filter(config)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(image_path),
        "-vf", vf,
        "-q:v", "2",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"Cover from image failed: {stderr.decode()[-300:]}")

    return output_path
