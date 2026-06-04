"""FFmpeg 多轨混音模块

将视频原始音轨、配音、音效、BGM 混合为最终音频并合成到视频。
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from layers.L4_audio.sfx import SFXItem

logger = logging.getLogger(__name__)


@dataclass
class AudioTrack:
    """单条音频轨道"""
    file_path: Path
    volume: float = 1.0
    delay_ms: int = 0
    duration_sec: float | None = None
    loop: bool = False
    label: str = ""


@dataclass
class MixConfig:
    """混音配置"""
    video_path: Path
    output_path: Path
    voiceover: AudioTrack | None = None
    bgm: AudioTrack | None = None
    sfx_tracks: list[AudioTrack] = field(default_factory=list)
    keep_original_audio: bool = False
    total_duration_sec: float | None = None


def _get_duration(file_path: Path) -> float:
    """用 ffprobe 获取媒体文件时长（秒）"""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(file_path),
        ],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        logger.warning("Cannot get duration for %s", file_path)
        return 0.0


def _build_filter_complex(config: MixConfig) -> tuple[list[str], str]:
    """构建 ffmpeg filter_complex 和输入参数

    Returns:
        (input_args, filter_complex_string)
    """
    input_args: list[str] = ["-i", str(config.video_path)]
    input_idx = 1
    filter_parts: list[str] = []
    mix_inputs: list[str] = []
    n_audio_streams = 0

    video_duration = config.total_duration_sec
    if not video_duration:
        video_duration = _get_duration(config.video_path)

    if config.keep_original_audio:
        filter_parts.append(f"[0:a]volume=1.0[orig]")
        mix_inputs.append("[orig]")
        n_audio_streams += 1

    if config.voiceover and config.voiceover.file_path.exists():
        input_args.extend(["-i", str(config.voiceover.file_path)])
        vol = config.voiceover.volume
        delay = config.voiceover.delay_ms
        label = f"vo"
        if delay > 0:
            filter_parts.append(
                f"[{input_idx}:a]adelay={delay}|{delay},volume={vol}[{label}]"
            )
        else:
            filter_parts.append(f"[{input_idx}:a]volume={vol}[{label}]")
        mix_inputs.append(f"[{label}]")
        n_audio_streams += 1
        input_idx += 1

    if config.bgm and config.bgm.file_path and config.bgm.file_path.exists():
        input_args.extend(["-i", str(config.bgm.file_path)])
        vol = config.bgm.volume
        label = "bgm"
        bgm_filter = f"[{input_idx}:a]"
        if config.bgm.loop:
            input_args.insert(-1, "-stream_loop")
            input_args.insert(-1, "-1")
        bgm_filter += f"atrim=0:{video_duration},asetpts=PTS-STARTPTS,"
        bgm_filter += f"volume={vol}[{label}]"
        filter_parts.append(bgm_filter)
        mix_inputs.append(f"[{label}]")
        n_audio_streams += 1
        input_idx += 1

    for i, sfx_track in enumerate(config.sfx_tracks):
        if not sfx_track.file_path or not sfx_track.file_path.exists():
            continue
        input_args.extend(["-i", str(sfx_track.file_path)])
        vol = sfx_track.volume
        delay = sfx_track.delay_ms
        label = f"sfx{i}"

        parts = []
        if delay > 0:
            parts.append(f"adelay={delay}|{delay}")
        if sfx_track.duration_sec:
            parts.append(f"atrim=0:{sfx_track.duration_sec}")
            parts.append("asetpts=PTS-STARTPTS")
        parts.append(f"volume={vol}")

        filter_parts.append(f"[{input_idx}:a]{','.join(parts)}[{label}]")
        mix_inputs.append(f"[{label}]")
        n_audio_streams += 1
        input_idx += 1

    if n_audio_streams == 0:
        return input_args, ""

    if n_audio_streams == 1:
        only_label = mix_inputs[0]
        filter_str = ";".join(filter_parts)
        filter_str += f";{only_label}acopy[aout]"
    else:
        filter_str = ";".join(filter_parts)
        filter_str += f";{''.join(mix_inputs)}amix=inputs={n_audio_streams}:duration=first:dropout_transition=2[aout]"

    return input_args, filter_str


async def mix(config: MixConfig) -> Path:
    """执行多轨混音，输出合成后的视频文件"""
    config.output_path.parent.mkdir(parents=True, exist_ok=True)

    input_args, filter_str = _build_filter_complex(config)

    if not filter_str:
        logger.info("No audio tracks, copying video as-is")
        cmd = ["ffmpeg", "-y", *input_args, "-c", "copy", str(config.output_path)]
    else:
        cmd = [
            "ffmpeg", "-y",
            *input_args,
            "-filter_complex", filter_str,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(config.output_path),
        ]

    logger.info("FFmpeg mix cmd: %s", " ".join(cmd))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode("utf-8", errors="replace")[-500:]
        raise RuntimeError(f"FFmpeg mix failed (code {proc.returncode}): {error_msg}")

    logger.info("Mix done: %s", config.output_path)
    return config.output_path


async def mix_simple(
    video_path: Path | str,
    output_path: Path | str,
    voiceover_path: Path | str | None = None,
    bgm_path: Path | str | None = None,
    bgm_volume: float = 0.3,
    sfx_items: list[SFXItem] | None = None,
) -> Path:
    """简化接口：一步完成混音"""
    video_path = Path(video_path)
    output_path = Path(output_path)

    vo_track = None
    if voiceover_path:
        vo_track = AudioTrack(file_path=Path(voiceover_path), volume=1.0, label="voiceover")

    bgm_track = None
    if bgm_path:
        bgm_track = AudioTrack(
            file_path=Path(bgm_path), volume=bgm_volume, loop=True, label="bgm",
        )

    sfx_tracks: list[AudioTrack] = []
    if sfx_items:
        for item in sfx_items:
            if item.file_path and item.file_path.exists():
                sfx_tracks.append(AudioTrack(
                    file_path=item.file_path,
                    volume=0.6,
                    delay_ms=int(item.timestamp_sec * 1000),
                    duration_sec=item.duration_sec,
                    label=item.category,
                ))

    config = MixConfig(
        video_path=video_path,
        output_path=output_path,
        voiceover=vo_track,
        bgm=bgm_track,
        sfx_tracks=sfx_tracks,
    )

    return await mix(config)


def get_audio_info(file_path: Path | str) -> dict:
    """获取音频文件基本信息"""
    file_path = Path(file_path)
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration,bit_rate:stream=codec_name,sample_rate,channels",
            "-of", "json",
            str(file_path),
        ],
        capture_output=True, text=True,
    )
    try:
        import json
        return json.loads(result.stdout)
    except Exception:
        return {}
