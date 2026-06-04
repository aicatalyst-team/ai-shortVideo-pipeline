"""Phase P Sprint P3：先 TTS 估时再选视频时长（消除音画错位的根源）

旧链路：LLM 估 estimated_duration_sec → 视频按这个 duration_sec 生成（被 kling 量化 5/10s）
→ TTS 朗读实际 N 秒 → drift = N - 5 or N - 10
新链路：LLM 给 narration_segment → 本模块按字数估 audio 时长 → 选 5/10s 视频档
→ 视频和音频在源头对齐

不在本模块做真 TTS 预合成、LLM 改写 narration 或拆段。
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

CHINESE_CHARS_PER_SEC: float = 7.5
VIDEO_5S_THRESHOLD: float = 4.6
VIDEO_10S_THRESHOLD: float = 9.3


class NarrationTooLongError(RuntimeError):
    """est_audio > 9.3s 时 strict=True 可选抛出。"""

    def __init__(self, narration: str, est_audio_sec: float):
        self.narration = narration
        self.est_audio_sec = est_audio_sec
        super().__init__(
            f"narration 估算 {est_audio_sec:.2f}s 超过最大视频档 9.3s，"
            f"建议压缩到 70 字以内或拆成两段。文本：{narration[:50]}..."
        )


class ClipPlan(BaseModel):
    """单个 clip 的时长规划结果。"""

    clip_no: int = Field(..., ge=1)
    narration: str
    char_count: int = Field(..., ge=0)
    est_audio_sec: float = Field(..., ge=0.0)
    target_video_sec: int = Field(..., description="5 或 10")
    is_fallback: bool = Field(default=False, description="True 表示触发了 > 9.3s 兜底")


def estimate_narration_audio_sec(
    text: str,
    *,
    chars_per_sec: float = CHINESE_CHARS_PER_SEC,
    speed_factor: float = 1.0,
) -> float:
    """根据 narration 文本字数估算 TTS 朗读时长（秒）。"""
    text = (text or "").strip()
    if not text:
        return 0.0
    rate = chars_per_sec * max(speed_factor, 0.1)
    return len(text) / rate


def pick_video_duration(est_audio_sec: float, *, strict: bool = False) -> tuple[int, bool]:
    """根据估时选 5/10s 视频档，返回 (target_video_sec, is_fallback)。"""
    if est_audio_sec <= VIDEO_5S_THRESHOLD:
        return 5, False
    if est_audio_sec <= VIDEO_10S_THRESHOLD:
        return 10, False
    if strict:
        raise NarrationTooLongError(narration="", est_audio_sec=est_audio_sec)
    log.warning(
        "[visual_planner] est_audio=%.2fs 超过 10s 档上限 9.3s，兜底选 10s（P1 av_sync 会末端报警）",
        est_audio_sec,
    )
    return 10, True


def plan_clip_durations(
    clips: list[dict[str, Any]],
    *,
    chars_per_sec: float = CHINESE_CHARS_PER_SEC,
    speed_factor: float = 1.0,
    strict: bool = False,
) -> list[ClipPlan]:
    """批量规划每个 clip 的视频时长（基于 narration 估时），不修改输入 clips。"""
    out: list[ClipPlan] = []
    for clip in clips:
        clip_no = int(clip.get("clip_no", len(out) + 1))
        narration = (clip.get("narration_segment") or "").strip()
        est_audio = estimate_narration_audio_sec(
            narration,
            chars_per_sec=chars_per_sec,
            speed_factor=speed_factor,
        )
        if strict and est_audio > VIDEO_10S_THRESHOLD:
            raise NarrationTooLongError(narration=narration, est_audio_sec=est_audio)
        target_video, is_fallback = pick_video_duration(est_audio, strict=False)
        out.append(
            ClipPlan(
                clip_no=clip_no,
                narration=narration,
                char_count=len(narration),
                est_audio_sec=round(est_audio, 2),
                target_video_sec=target_video,
                is_fallback=is_fallback,
            )
        )
    return out


def format_plan_for_feishu(plans: list[ClipPlan]) -> str:
    """格式化时长规划报告，飞书消息显示用。"""
    if not plans:
        return "（无 clip 需要规划）"
    lines = ["📐 P3 时长规划（先估 TTS 再选视频档）："]
    for p in plans:
        flag = " ⚠️兜底" if p.is_fallback else ""
        lines.append(
            f"  clip {p.clip_no}: {p.char_count} 字 → 估 TTS {p.est_audio_sec:.2f}s "
            f"→ 选 {p.target_video_sec}s 视频{flag}"
        )
    return "\n".join(lines)
