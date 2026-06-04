"""音画同步防御层（Phase P Sprint P1）

提供：
- ffprobe 探针：probe_video_duration / probe_audio_duration / probe_media_duration
- 漂移报告：build_av_sync_report 输出 AvSyncReport（pass / soft_fix / hard_fail 三档）
- 温和补齐：apply_av_sync_correction 处理 0.5-1.2s 漂移（视频长则裁、视频短则补静音）
- 异常：AVDriftTooLargeError（drift > 1.2s 时抛，上层不发成片）

不重构既有 mix_simple / 字幕 / 拼接逻辑。本模块是观测 + 防御层。
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# 三档阈值（单位：秒）
DRIFT_PASS_THRESHOLD: float = 0.5
DRIFT_HARD_LIMIT: float = 1.2

Severity = Literal["pass", "soft_fix", "hard_fail"]


class AVDriftTooLargeError(RuntimeError):
    """音画漂移超过 DRIFT_HARD_LIMIT，不允许发最终成片。"""

    def __init__(self, report: "AvSyncReport"):
        self.report = report
        super().__init__(
            f"音画漂移 {report.drift_sec:+.2f}s 超过硬阈值 ±{DRIFT_HARD_LIMIT}s，"
            f"video={report.video_sec:.2f}s voiceover={report.voiceover_sec:.2f}s。"
            f"建议：重新规划旁白长度或重生成视频。"
        )


class AvSyncReport(BaseModel):
    """音画同步报告，飞书消息显示用。"""

    video_sec: float = Field(..., description="原视频时长（拼接后 final.mp4）")
    voiceover_sec: float = Field(..., description="TTS 配音时长")
    final_sec: float = Field(..., description="混音后实际成片时长（含本次补齐后）")
    drift_sec: float = Field(..., description="voiceover - video（负=视频长于音频）")
    severity: Severity = Field(..., description="pass / soft_fix / hard_fail")
    correction_applied: str = Field(default="none", description="实际做了什么补齐")

    def to_feishu_line(self) -> str:
        """格式化成飞书一行消息：视频 X.Xs / 配音 X.Xs / 漂移 ±X.Xs <icon>"""
        icon = {"pass": "✅", "soft_fix": "⚠️", "hard_fail": "🔴"}[self.severity]
        return (
            f"{icon} 视频 {self.video_sec:.2f}s / 配音 {self.voiceover_sec:.2f}s "
            f"/ 漂移 {self.drift_sec:+.2f}s ({self.severity})"
        )


def probe_media_duration(path: Path | str) -> float:
    """通用：探任意媒体文件时长（秒）。失败返回 0.0 + log warning，不抛。"""
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        log.warning("[av_sync] probe 失败：文件不存在或空 %s", path)
        return 0.0
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        duration = float(result.stdout.strip())
        if duration <= 0:
            log.warning("[av_sync] probe 失败：duration=%s for %s", result.stdout.strip(), path)
            return 0.0
        return duration
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as exc:
        log.warning("[av_sync] probe 失败 %s: %s", path, exc)
        return 0.0


def probe_video_duration(path: Path | str) -> float:
    """专用：探视频时长。当前实现 = probe_media_duration（mp4 的 format duration 就是视频时长）"""
    return probe_media_duration(path)


def probe_audio_duration(path: Path | str) -> float:
    """专用：探音频时长。当前实现 = probe_media_duration"""
    return probe_media_duration(path)


def _classify_severity(drift_sec: float) -> Severity:
    abs_drift = abs(drift_sec)
    if abs_drift <= DRIFT_PASS_THRESHOLD:
        return "pass"
    if abs_drift <= DRIFT_HARD_LIMIT:
        return "soft_fix"
    return "hard_fail"


def build_av_sync_report(
    video_path: Path | str,
    voiceover_path: Path | str | None,
    final_path: Path | str,
    correction_applied: str = "none",
) -> AvSyncReport:
    """统一构建漂移报告。"""
    video_sec = probe_video_duration(video_path)
    voiceover_sec = probe_audio_duration(voiceover_path) if voiceover_path else 0.0
    final_sec = probe_media_duration(final_path) if Path(final_path).exists() else 0.0

    if voiceover_sec <= 0:
        return AvSyncReport(
            video_sec=video_sec,
            voiceover_sec=0.0,
            final_sec=final_sec,
            drift_sec=0.0,
            severity="pass",
            correction_applied="no_voiceover",
        )

    drift = voiceover_sec - video_sec
    return AvSyncReport(
        video_sec=video_sec,
        voiceover_sec=voiceover_sec,
        final_sec=final_sec,
        drift_sec=drift,
        severity=_classify_severity(drift),
        correction_applied=correction_applied,
    )


def apply_av_sync_correction(
    mixed_path: Path | str,
    voiceover_sec: float,
    output_path: Path | str,
    drift_sec: float,
) -> Path:
    """对 0.5 < |drift| <= 1.2 的漂移做温和补齐。"""
    mixed_path = Path(mixed_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if drift_sec < 0:
        log.info(
            "[av_sync] soft_fix: 视频长 %.2fs，裁到 voiceover %.2fs",
            -drift_sec, voiceover_sec,
        )
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(mixed_path),
                "-t", f"{voiceover_sec:.3f}",
                "-c", "copy",
                str(output_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return output_path

    log.info("[av_sync] soft_fix: 音频长 %.2fs，原视频末尾静默播完（不裁）", drift_sec)
    import shutil

    shutil.copy(str(mixed_path), str(output_path))
    return output_path


def check_and_correct_av_sync(
    video_path: Path | str,
    voiceover_path: Path | str,
    mixed_path: Path | str,
    corrected_output_path: Path | str,
) -> AvSyncReport:
    """webhooks.py 主调用入口。一站式检查、分档、温和修正或 hard fail。"""
    report = build_av_sync_report(video_path, voiceover_path, mixed_path)
    log.info("[av_sync] report: %s", report.to_feishu_line())

    if report.severity == "pass":
        return report

    if report.severity == "hard_fail":
        raise AVDriftTooLargeError(report)

    voiceover_sec = report.voiceover_sec
    apply_av_sync_correction(
        mixed_path=mixed_path,
        voiceover_sec=voiceover_sec,
        output_path=corrected_output_path,
        drift_sec=report.drift_sec,
    )
    return build_av_sync_report(
        video_path=video_path,
        voiceover_path=voiceover_path,
        final_path=corrected_output_path,
        correction_applied=(
            f"trim_video_to_{voiceover_sec:.2f}s"
            if report.drift_sec < 0
            else "passthrough_long_audio"
        ),
    )
