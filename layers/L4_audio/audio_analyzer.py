"""输入视频的音频分析模块。

与同目录 bgm.py 的区别：
- bgm.py 是给**输出视频**配 BGM（从素材库选 BGM）
- 本模块是分析**输入视频**自带的 BGM/语音（FFmpeg 抽音 + librosa BPM + Whisper 转写）

分析结果会传入 lobster_rewrite_vlm，让改写链知道原视频的节奏和歌词，
从而生成节奏匹配的方案（避免热舞视频被改成抒情慢舞）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from core.parsers import AudioUnderstanding

log = logging.getLogger(__name__)


_FFMPEG_FALLBACK_PATHS = [
    "ffmpeg",
    "/usr/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "C:\\ffmpeg\\bin\\ffmpeg.exe",
]


def _find_ffmpeg() -> str:
    for p in _FFMPEG_FALLBACK_PATHS:
        if p == "ffmpeg":
            return p
        if os.path.isfile(p):
            return p
    raise FileNotFoundError("找不到 ffmpeg")


def _bpm_to_label(bpm: float) -> str:
    if bpm <= 0:
        return "未知"
    if bpm < 70:
        return "慢"
    if bpm < 100:
        return "中"
    if bpm < 130:
        return "快"
    return "超快"


# Whisper 模型缓存为模块级单例，避免每次重新加载
_whisper_model = None
_whisper_model_size = None


def _get_whisper_model(model_size: str):
    """faster-whisper 模型懒加载 + 单例缓存。

    优先级：
      1) 环境变量 WHISPER_MODEL_PATH（本地目录）—— 离线/手传模型时用
      2) 函数参数 model_size（如 "small"）—— 走 HF/HF_ENDPOINT 在线下载
    """
    global _whisper_model, _whisper_model_size

    local_path = os.environ.get("WHISPER_MODEL_PATH", "").strip()
    model_id = local_path if local_path else model_size

    if _whisper_model is not None and _whisper_model_size == model_id:
        return _whisper_model

    from faster_whisper import WhisperModel

    log.info("[音频分析] 加载 faster-whisper 模型: %s（首次加载若需下载会比较慢）", model_id)
    _whisper_model = WhisperModel(model_id, device="cpu", compute_type="int8")
    _whisper_model_size = model_id
    return _whisper_model


async def _extract_audio(video_path: Path, out_path: Path) -> bool:
    """用 FFmpeg 抽音频为 16kHz mono WAV。返回是否成功。"""
    ffmpeg_bin = _find_ffmpeg()
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_bin,
        "-y",
        "-i", str(video_path),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-acodec", "pcm_s16le",
        str(out_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if not (out_path.is_file() and out_path.stat().st_size > 1000):
        log.warning("[音频分析] FFmpeg 抽音失败：%s", stderr.decode(errors="replace")[:200])
        return False
    return True


def _detect_bpm_and_energy(wav_path: Path) -> tuple[float, float, float]:
    """用 librosa 检测 BPM、平均能量(dB)、时长。同步函数，需在 executor 中调用。"""
    import librosa
    import numpy as np

    y, sr = librosa.load(str(wav_path), sr=None, mono=True)
    duration = float(len(y) / sr) if sr else 0.0

    try:
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        # librosa>=0.10 返回 0-d ndarray 或 1-d ndarray，统一压平后取首元素
        if tempo is None:
            bpm = 0.0
        else:
            arr = np.atleast_1d(np.asarray(tempo)).flatten()
            bpm = float(arr[0]) if arr.size > 0 else 0.0
    except Exception as e:
        log.warning("[音频分析] BPM 检测失败：%s", e)
        bpm = 0.0

    try:
        rms = librosa.feature.rms(y=y).flatten()
        if len(rms) > 0:
            avg_rms = float(np.mean(rms))
            energy_db = 20.0 * float(np.log10(max(avg_rms, 1e-6)))
        else:
            energy_db = -60.0
    except Exception as e:
        log.warning("[音频分析] RMS 能量计算失败：%s", e)
        energy_db = -60.0

    return bpm, energy_db, duration


def _transcribe(wav_path: Path, model_size: str) -> tuple[str, str, float]:
    """用 faster-whisper 转写音频。返回 (text, language, language_probability)。

    针对 BGM/音乐场景的调优：
    - 关闭 VAD（默认 VAD 会把背景音乐当成静音过滤掉，导致歌词全部丢失）
    - 提升 beam_size 到 5 提升识别准确率
    - 不预设 language，让模型自动检测
    - 关闭 condition_on_previous_text 避免幻觉
    """
    model = _get_whisper_model(model_size)
    segments, info = model.transcribe(
        str(wav_path),
        beam_size=5,
        vad_filter=False,
        condition_on_previous_text=False,
        no_speech_threshold=0.6,
    )
    text_parts = [seg.text for seg in segments]
    text = "".join(text_parts).strip()
    lang_prob = float(info.language_probability or 0.0)
    log.info("[音频分析] Whisper lang=%s prob=%.2f text=%r",
             info.language, lang_prob, text[:80])
    return text, info.language or "", lang_prob


async def analyze_audio(
    video_path: str | Path,
    whisper_model: str = "small",
    skip_whisper: bool = False,
) -> AudioUnderstanding:
    """从视频抽音频并分析 BGM 节奏 + 人声/歌词。

    Args:
        video_path: 视频文件路径
        whisper_model: faster-whisper 模型大小（tiny/base/small/medium/large-v3）
        skip_whisper: 仅做 BPM/能量分析，跳过歌词转写（用于减负或调试）

    任何环节失败都返回降级结果（has_audio=False 或部分字段为空），不会抛异常打断主流程。
    """
    video_path = Path(video_path)
    if not video_path.is_file():
        log.warning("[音频分析] 视频不存在：%s", video_path)
        return AudioUnderstanding(
            has_audio=False, bpm=0.0, tempo_label="无", energy_db=-60.0,
            has_vocals=False, lyrics_excerpt="", language="", duration_sec=0.0,
        )

    tmp_dir = Path(tempfile.mkdtemp(prefix="audio_analysis_"))
    try:
        wav_path = tmp_dir / "audio.wav"
        ok = await _extract_audio(video_path, wav_path)
        if not ok:
            return AudioUnderstanding(
                has_audio=False, bpm=0.0, tempo_label="无", energy_db=-60.0,
                has_vocals=False, lyrics_excerpt="", language="", duration_sec=0.0,
            )

        loop = asyncio.get_event_loop()

        try:
            bpm, energy_db, duration = await loop.run_in_executor(
                None, _detect_bpm_and_energy, wav_path
            )
        except ImportError:
            log.warning("[音频分析] 未安装 librosa，跳过 BPM 检测")
            bpm, energy_db, duration = 0.0, -60.0, 0.0
        except Exception as e:
            log.warning("[音频分析] librosa 分析异常：%s", e)
            bpm, energy_db, duration = 0.0, -60.0, 0.0

        text, language, lang_prob = "", "", 0.0
        if not skip_whisper:
            try:
                text, language, lang_prob = await loop.run_in_executor(
                    None, _transcribe, wav_path, whisper_model
                )
            except ImportError:
                log.warning("[音频分析] 未安装 faster-whisper，跳过歌词转写")
            except Exception as e:
                log.warning("[音频分析] Whisper 转写异常：%s", e)

        text = text.strip()
        # 低置信度（<0.5）的转写结果几乎都是噪声/幻觉，不当作歌词使用
        # 同时要求文本足够长（>5 字符）才认为有"真实人声"
        if lang_prob < 0.5:
            log.info("[音频分析] 语言置信度过低(%.2f)，丢弃歌词文本（视为纯 BGM）", lang_prob)
            text = ""
            language = ""
        has_vocals = len(text) > 5

        result = AudioUnderstanding(
            has_audio=True,
            bpm=round(bpm, 1),
            tempo_label=_bpm_to_label(bpm),
            energy_db=round(energy_db, 1),
            has_vocals=has_vocals,
            lyrics_excerpt=text[:200],
            language=language,
            duration_sec=round(duration, 1),
        )

        log.info(
            "[音频分析] BPM=%.1f(%s) 能量=%.1fdB 时长=%.1fs 人声=%s 语言=%s 文本=%d字",
            result.bpm, result.tempo_label, result.energy_db, result.duration_sec,
            result.has_vocals, result.language or "-", len(text),
        )
        return result

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
