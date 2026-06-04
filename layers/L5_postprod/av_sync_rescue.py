"""D41-C AV sync rescue strategies.

This module sits above av_sync.py. It never changes the hard-fail contract of
check_and_correct_av_sync; instead it attempts best-effort rescue after a hard
drift is detected so already-generated video is not wasted.
"""
from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from config.settings import get_settings
from integrations.llm_client import get_deepseek
from layers.L4_audio.mixer import mix_simple
from layers.L4_audio.voiceover import synthesize
from layers.L5_postprod.av_sync import (
    DRIFT_HARD_LIMIT,
    build_av_sync_report,
    probe_audio_duration,
    probe_video_duration,
)

log = logging.getLogger(__name__)


class RescueStrategy(str, Enum):
    NO_OP = "no_op"
    AUDIO_TEMPO = "audio_tempo"
    AUDIO_TEMPO_VIDEO_PAD = "audio_pad"
    NARRATION_REWRITE = "narration_rewrite"
    HARD_FAIL = "hard_fail"


@dataclass
class RescueResult:
    success: bool
    strategy: RescueStrategy
    new_mixed_path: str | None
    new_drift_sec: float | None
    cost_cny: float = 0.0
    message: str = ""


def _calc_atempo(video_sec: float, audio_sec: float) -> float:
    """Return safe atempo factor for audio_sec / tempo ~= video_sec."""
    tempo = audio_sec / video_sec if video_sec > 0 else 1.0
    cfg = get_settings()
    return max(0.85, min(float(cfg.av_rescue_tempo_max), tempo))


def _select_strategy(drift_sec: float) -> RescueStrategy:
    abs_drift = abs(float(drift_sec or 0.0))
    cfg = get_settings()
    if abs_drift <= DRIFT_HARD_LIMIT:
        return RescueStrategy.NO_OP
    if abs_drift <= 3.0:
        return RescueStrategy.AUDIO_TEMPO
    if abs_drift <= 8.0:
        return RescueStrategy.AUDIO_TEMPO_VIDEO_PAD
    if abs_drift <= float(cfg.av_rescue_rewrite_max_drift_sec):
        return RescueStrategy.NARRATION_REWRITE
    return RescueStrategy.HARD_FAIL


def _strategy_chain(first: RescueStrategy) -> list[RescueStrategy]:
    order = [
        RescueStrategy.AUDIO_TEMPO,
        RescueStrategy.AUDIO_TEMPO_VIDEO_PAD,
        RescueStrategy.NARRATION_REWRITE,
    ]
    if first not in order:
        return []
    return order[order.index(first):]


def _run_ffmpeg(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _tempo_filter(tempo: float) -> str:
    """Build ffmpeg atempo chain. Our configured max is 1.30, but keep generic."""
    parts: list[str] = []
    remaining = float(tempo)
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(f"atempo={remaining:.4f}")
    return ",".join(parts)


def _atempo_audio(input_audio: str, output_audio: str, tempo: float) -> str:
    Path(output_audio).parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg([
        "ffmpeg", "-y",
        "-i", input_audio,
        "-filter:a", _tempo_filter(tempo),
        "-vn",
        output_audio,
    ])
    return output_audio


def _pad_video(input_video: str, output_video: str, pad_sec: float) -> str:
    Path(output_video).parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg([
        "ffmpeg", "-y",
        "-i", input_video,
        "-vf", f"tpad=stop_mode=clone:stop_duration={max(0.0, pad_sec):.3f}",
        "-c:a", "copy",
        output_video,
    ])
    return output_video


async def _mix_video_audio(video_path: str, audio_path: str, output_path: str) -> str:
    await mix_simple(video_path=video_path, output_path=output_path, voiceover_path=audio_path)
    return output_path


def _verify(video_path: str, audio_path: str, mixed_path: str) -> float | None:
    report = build_av_sync_report(video_path, audio_path, mixed_path)
    if abs(report.drift_sec) <= DRIFT_HARD_LIMIT:
        return report.drift_sec
    return None


async def _rewrite_narration(narration_text: str, target_chars: int) -> str:
    prompt = (
        "你是短视频文案精简师。请在保留核心信息和节奏感的前提下，"
        f"把下面旁白缩写到 {target_chars} 字以内。只输出改写后的旁白，不要解释。\n\n"
        f"{narration_text}"
    )
    response = await get_deepseek().chat.completions.create(
        model=get_settings().deepseek_model,
        messages=[
            {"role": "system", "content": "你只输出最终旁白文本。"},
            {"role": "user", "content": prompt},
        ],
        max_tokens=600,
    )
    text = (response.choices[0].message.content or "").strip()
    return text[:target_chars] if text else narration_text[:target_chars]


async def _try_audio_tempo(
    *,
    video_path: str,
    voiceover_path: str,
    output_dir: str,
    strategy: RescueStrategy = RescueStrategy.AUDIO_TEMPO,
) -> RescueResult:
    video_sec = probe_video_duration(video_path)
    audio_sec = probe_audio_duration(voiceover_path)
    tempo = _calc_atempo(video_sec, audio_sec)
    adjusted_audio = os.path.join(output_dir, f"rescue_{strategy.value}_voiceover.mp3")
    mixed_out = os.path.join(output_dir, f"rescue_{strategy.value}.mp4")
    _atempo_audio(voiceover_path, adjusted_audio, tempo)
    await _mix_video_audio(video_path, adjusted_audio, mixed_out)
    new_drift = _verify(video_path, adjusted_audio, mixed_out)
    if new_drift is None:
        return RescueResult(False, strategy, None, None, message="atempo 后漂移仍超阈值")
    return RescueResult(True, strategy, mixed_out, new_drift, message=f"audio tempo={tempo:.2f}")


async def _try_audio_pad(
    *,
    video_path: str,
    voiceover_path: str,
    output_dir: str,
) -> RescueResult:
    video_sec = probe_video_duration(video_path)
    audio_sec = probe_audio_duration(voiceover_path)
    cfg = get_settings()
    tempo = _calc_atempo(video_sec, audio_sec)
    adjusted_audio = os.path.join(output_dir, "rescue_audio_pad_voiceover.mp3")
    _atempo_audio(voiceover_path, adjusted_audio, tempo)
    adjusted_audio_sec = probe_audio_duration(adjusted_audio)
    pad_sec = max(0.0, min(float(cfg.av_rescue_pad_max_sec), adjusted_audio_sec - video_sec))
    padded_video = os.path.join(output_dir, "rescue_audio_pad_video.mp4")
    mixed_out = os.path.join(output_dir, "rescue_audio_pad.mp4")
    _pad_video(video_path, padded_video, pad_sec)
    await _mix_video_audio(padded_video, adjusted_audio, mixed_out)
    new_drift = _verify(padded_video, adjusted_audio, mixed_out)
    if new_drift is None:
        return RescueResult(False, RescueStrategy.AUDIO_TEMPO_VIDEO_PAD, None, None, message="pad 后漂移仍超阈值")
    return RescueResult(
        True,
        RescueStrategy.AUDIO_TEMPO_VIDEO_PAD,
        mixed_out,
        new_drift,
        message=f"audio tempo={tempo:.2f}, video pad={pad_sec:.2f}s",
    )


async def _try_rewrite(
    *,
    video_path: str,
    voiceover_path: str,
    narration_text: str,
    output_dir: str,
    tts_voice_key: str,
) -> RescueResult:
    video_sec = probe_video_duration(video_path)
    audio_sec = probe_audio_duration(voiceover_path)
    if video_sec <= 0 or audio_sec <= 0 or not narration_text.strip():
        return RescueResult(False, RescueStrategy.NARRATION_REWRITE, None, None, message="缺少 rewrite 所需时长或旁白")
    target_chars = max(8, int(len(narration_text) * (video_sec / audio_sec) * 0.92))
    log.info(
        "[av_rescue][rewrite] %d chars -> target %d chars; tts voice=%s",
        len(narration_text),
        target_chars,
        tts_voice_key or "default",
    )
    rewritten = await _rewrite_narration(narration_text, target_chars)
    log.info("[av_rescue][rewrite] result %d chars: %s", len(rewritten), rewritten[:80])
    new_audio = os.path.join(output_dir, "rescue_rewrite_voiceover.mp3")
    await synthesize(text=rewritten, output_path=new_audio, voice=tts_voice_key)
    mixed_out = os.path.join(output_dir, "rescue_rewrite.mp4")
    await _mix_video_audio(video_path, new_audio, mixed_out)
    new_drift = _verify(video_path, new_audio, mixed_out)
    if new_drift is None:
        return RescueResult(False, RescueStrategy.NARRATION_REWRITE, None, None, message="rewrite 后漂移仍超阈值")
    return RescueResult(
        True,
        RescueStrategy.NARRATION_REWRITE,
        mixed_out,
        new_drift,
        cost_cny=round((len(rewritten) / 1000.0) * 0.30, 2),
        message=f"rewrite narration to <= {target_chars} chars",
    )


async def attempt_rescue(
    *,
    mixed_path: str,
    video_path: str,
    voiceover_path: str,
    narration_text: str,
    drift_sec: float,
    output_dir: str,
    tts_voice_key: str = "",
    storyboard_id: str | None = None,
) -> RescueResult:
    """Select and execute an AV sync rescue strategy. Never raises."""
    del mixed_path, storyboard_id  # Current rescue uses source video/audio; kept for interface context.
    if not get_settings().av_rescue_enabled:
        return RescueResult(False, RescueStrategy.HARD_FAIL, None, None, message="av rescue disabled")

    first = _select_strategy(drift_sec)
    if first == RescueStrategy.NO_OP:
        return RescueResult(True, RescueStrategy.NO_OP, None, drift_sec, message="no rescue needed")
    if first == RescueStrategy.HARD_FAIL:
        return RescueResult(False, RescueStrategy.HARD_FAIL, None, None, message="drift exceeds rewrite rescue range")

    last_message = ""
    for strategy in _strategy_chain(first):
        try:
            log.info("[av_rescue] trying strategy=%s drift=%+.2fs", strategy.value, drift_sec)
            if strategy == RescueStrategy.AUDIO_TEMPO:
                result = await _try_audio_tempo(
                    video_path=video_path,
                    voiceover_path=voiceover_path,
                    output_dir=output_dir,
                    strategy=strategy,
                )
            elif strategy == RescueStrategy.AUDIO_TEMPO_VIDEO_PAD:
                result = await _try_audio_pad(
                    video_path=video_path,
                    voiceover_path=voiceover_path,
                    output_dir=output_dir,
                )
            else:
                result = await _try_rewrite(
                    video_path=video_path,
                    voiceover_path=voiceover_path,
                    narration_text=narration_text,
                    output_dir=output_dir,
                    tts_voice_key=tts_voice_key,
                )
            if result.success:
                log.info("[av_rescue] success strategy=%s new_drift=%s", strategy.value, result.new_drift_sec)
                return result
            last_message = result.message
            log.warning("[av_rescue] strategy=%s failed: %s", strategy.value, result.message)
        except Exception as exc:
            last_message = str(exc)
            log.warning("[av_rescue] strategy=%s exception: %s", strategy.value, exc)

    return RescueResult(False, RescueStrategy.HARD_FAIL, None, None, message=last_message or "all rescue strategies failed")
