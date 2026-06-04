"""节奏化剪辑

根据 rhythm_engine 输出的注意力曲线，对视频进行节奏增强：
- cut: 在指定时间点插入快速切换（通过 FFmpeg 剪辑）
- caption_zoom: 关键字幕时间段放大滤镜
- bgm_swell: 标记 BGM 升调时间点（传给 mixer）
- sfx: 标记音效插入点（传给 mixer）
- pause: 在关键帧插入 0.5s 静帧停留

对于解说类/图文混剪视频，最主要的节奏手段是：
  1. 每段配图时长与旁白对齐（cut）
  2. 关键词字幕放大（caption_zoom，通过 captions.py 实现）
  3. 标记音效/BGM 时间点给 mixer
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from layers.L2_creative.rhythm_engine import RhythmPlan, AttentionPoint

log = logging.getLogger(__name__)


@dataclass
class RhythmEditResult:
    output_path: str
    applied_points: list[AttentionPoint] = field(default_factory=list)
    sfx_cues: list[dict] = field(default_factory=list)    # [{timestamp_sec, sfx_type}]
    bgm_swells: list[float] = field(default_factory=list)  # BGM 升调时间戳列表
    caption_zoom_ranges: list[dict] = field(default_factory=list)  # [{start, end, intensity}]


async def apply_rhythm(
    video_path: str,
    output_path: str,
    rhythm_plan: RhythmPlan,
) -> RhythmEditResult:
    """将注意力曲线应用到视频上。

    对于解说类视频，主要处理：
    - caption_zoom → 记录时间段，供 captions.py 放大
    - sfx → 记录 cue 点，供 mixer 插入音效
    - bgm_swell → 记录升调时间点，供 mixer 处理
    - cut/pause → 目前解说类配图以缓动为主，不做硬切，预留接口
    """
    log.info("[节奏剪辑] 处理 %s，%d 个刺激点", video_path, len(rhythm_plan.attention_points))

    result = RhythmEditResult(output_path=video_path)  # 默认不改动视频

    sfx_cues = []
    bgm_swells = []
    caption_zooms = []

    for pt in rhythm_plan.attention_points:
        if pt.point_type == "sfx":
            sfx_cues.append({
                "timestamp_sec": pt.timestamp_sec,
                "sfx_type": _map_sfx_type(pt.description, pt.intensity),
                "intensity": pt.intensity,
            })
        elif pt.point_type == "bgm_swell":
            bgm_swells.append(pt.timestamp_sec)
        elif pt.point_type == "caption_zoom":
            caption_zooms.append({
                "start": max(0, pt.timestamp_sec - 0.3),
                "end": pt.timestamp_sec + 1.5,
                "intensity": pt.intensity,
                "trigger_text": pt.narration_trigger,
            })
        elif pt.point_type == "cut" and len(rhythm_plan.attention_points) > 3:
            # 解说类：cut 点标记给上层做配图切换参考，不做 FFmpeg 硬切
            log.debug("[节奏剪辑] cut 点 %.1fs: %s", pt.timestamp_sec, pt.description)

    # pause 目前只做标记，不直接改写视频。
    # 现有 _insert_pauses 实现会重编码出新的 mp4，存在把正常视频变成极小损坏文件的风险，
    # 先禁用实际写盘，避免上传黑屏视频。
    pause_points = [pt for pt in rhythm_plan.attention_points if pt.point_type == "pause"]
    if pause_points:
        log.info("[节奏剪辑] 检测到 %d 个 pause 点，当前仅保留标记，不直接改写视频", len(pause_points))

    result.sfx_cues = sfx_cues
    result.bgm_swells = bgm_swells
    result.caption_zoom_ranges = caption_zooms
    result.applied_points = rhythm_plan.attention_points

    log.info(
        "[节奏剪辑] 完成：sfx=%d, bgm_swell=%d, caption_zoom=%d, pause=%d",
        len(sfx_cues), len(bgm_swells), len(caption_zooms), len(pause_points),
    )
    return result


def _map_sfx_type(description: str, intensity: int) -> str:
    """从描述推断音效类型。"""
    desc = description.lower()
    if any(w in desc for w in ["冲击", "震撼", "爆", "数据"]):
        return "impact" if intensity >= 4 else "whoosh"
    if any(w in desc for w in ["情感", "温馨", "感动"]):
        return "soft_chime"
    if any(w in desc for w in ["悬念", "神秘", "未知"]):
        return "suspense_sting"
    if any(w in desc for w in ["结尾", "总结", "落点"]):
        return "ending_chime"
    return "whoosh"


def _has_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


async def _insert_pauses(
    input_path: str,
    output_path: str,
    pause_points: list[AttentionPoint],
    pause_duration: float = 0.5,
) -> str:
    """在指定时间点插入静帧停留（freeze frame）。"""
    if not pause_points:
        return input_path

    with tempfile.TemporaryDirectory() as tmpdir:
        current = input_path
        for i, pt in enumerate(pause_points):
            freeze_out = os.path.join(tmpdir, f"freeze_{i}.mp4")
            ts = pt.timestamp_sec
            cmd = [
                "ffmpeg", "-y",
                "-i", current,
                "-vf", (
                    f"select='eq(n,0)',setpts=N/(FRAME_RATE*TB),"
                    f"tpad=stop_mode=clone:stop_duration={pause_duration}"
                    if i == 0 else
                    f"setpts=PTS+{pause_duration}/TB"
                ),
                "-af", f"adelay={int(pause_duration * 1000)}|{int(pause_duration * 1000)}",
                freeze_out,
            ]
            log.debug("[节奏剪辑] 插入静帧 %.1fs: %s", ts, " ".join(cmd))
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
                if proc.returncode == 0:
                    current = freeze_out
            except Exception as e:
                log.warning("[节奏剪辑] 静帧插入失败: %s", e)

        if current != input_path:
            import shutil
            shutil.copy2(current, output_path)
            return output_path

    return input_path


def get_cut_timestamps(rhythm_plan: RhythmPlan) -> list[float]:
    """提取所有 cut 时间点，供上层做配图切换参考。"""
    return [
        pt.timestamp_sec
        for pt in rhythm_plan.attention_points
        if pt.point_type == "cut"
    ]
