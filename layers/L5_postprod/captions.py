"""动态字幕系统（多风格）

支持多种字幕风格，通过风格模板切换。
- 有真实 word-level 时间戳时：生成 ASS 字幕，精准同步（修复硬伤3）
- 无时间戳时：降级为 drawtext 均分方案
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from layers.L5_postprod.text_normalizer import to_simplified_zh
from typing import Literal

logger = logging.getLogger(__name__)

CaptionStyle = Literal[
    "military",   # 军事风：白字粗黑边，底部居中
    "cute",       # 可爱风：粉色圆体，底部偏上
    "drama",      # 戏剧风：大号黄字，阴影，居中
    "danmaku",    # 弹幕风：小字横向滚动
    "minimal",    # 极简风：白字无边，底部
    "cinematic",  # 电影风：上下黑边 + 居中白字
]

FONT_PATHS = {
    "win": "C\\:/Windows/Fonts/msyh.ttc",
    "linux": "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
}


@dataclass
class CaptionItem:
    text: str
    start_sec: float
    end_sec: float


@dataclass
class CaptionConfig:
    items: list[CaptionItem]
    style: CaptionStyle = "military"
    font_path: str = ""
    font_size: int = 0
    position_y: str = ""


# ── 风格参数预设 ──
_STYLE_PARAMS: dict[str, dict] = {
    "military": {
        "fontsize": 42,
        "fontcolor": "white",
        "bordercolor": "black",
        "borderw": 3,
        "shadowx": 0, "shadowy": 0,
        "y_expr": "h-th-80",
        "x_expr": "(w-text_w)/2",
    },
    "cute": {
        "fontsize": 38,
        "fontcolor": "#FFB6C1",
        "bordercolor": "white",
        "borderw": 2,
        "shadowx": 0, "shadowy": 0,
        "y_expr": "h-th-120",
        "x_expr": "(w-text_w)/2",
    },
    "drama": {
        "fontsize": 52,
        "fontcolor": "#FFD700",
        "bordercolor": "black",
        "borderw": 4,
        "shadowx": 3, "shadowy": 3,
        "y_expr": "(h-th)/2",
        "x_expr": "(w-text_w)/2",
    },
    "danmaku": {
        "fontsize": 30,
        "fontcolor": "white",
        "bordercolor": "black",
        "borderw": 1,
        "shadowx": 0, "shadowy": 0,
        "y_expr": "50",
        "x_expr": "w-mod(t*200\\,w+text_w)-text_w",
    },
    "minimal": {
        "fontsize": 36,
        "fontcolor": "white@0.9",
        "bordercolor": "black@0.3",
        "borderw": 1,
        "shadowx": 0, "shadowy": 0,
        "y_expr": "h-th-60",
        "x_expr": "(w-text_w)/2",
    },
    "cinematic": {
        "fontsize": 40,
        "fontcolor": "white",
        "bordercolor": "black@0.0",
        "borderw": 0,
        "shadowx": 2, "shadowy": 2,
        "y_expr": "h-th-40",
        "x_expr": "(w-text_w)/2",
    },
}


def _detect_font() -> str:
    win_font = Path("C:/Windows/Fonts/msyh.ttc")
    if win_font.exists():
        return FONT_PATHS["win"]
    return FONT_PATHS["linux"]


def _escape_text(text: str) -> str:
    """转义 FFmpeg drawtext 特殊字符"""
    return (
        text
        .replace("\n", " ")
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace("%", "%%")
    )


def _trim_caption_text(text: str, max_chars: int = 16) -> str:
    clean = re.sub(r"\s+", "", to_simplified_zh(str(text or "").strip()))
    if len(clean) <= max_chars:
        return clean
    return clean[:max_chars]


def from_captions_list(
    captions: list[str],
    total_duration_sec: float,
) -> list[CaptionItem]:
    """将字幕列表均分时长，转为 CaptionItem 列表"""
    if not captions:
        return []
    per = total_duration_sec / len(captions)
    return [
        CaptionItem(
            text=cap,
            start_sec=round(i * per, 2),
            end_sec=round((i + 1) * per, 2),
        )
        for i, cap in enumerate(captions)
    ]


def build_drawtext_filters(config: CaptionConfig) -> str:
    """构建 FFmpeg -vf drawtext 滤镜串"""
    if not config.items:
        return ""

    style_key = config.style if config.style in _STYLE_PARAMS else "military"
    params = _STYLE_PARAMS[style_key]
    font = config.font_path or _detect_font()
    fontsize = config.font_size or params["fontsize"]

    filters = []
    for item in config.items:
        safe_text = _escape_text(_trim_caption_text(item.text))
        parts = [
            f"drawtext=text='{safe_text}'",
            f"fontfile={font}",
            f"fontsize={fontsize}",
            f"fontcolor={params['fontcolor']}",
            f"bordercolor={params['bordercolor']}",
            f"borderw={params['borderw']}",
            f"shadowx={params['shadowx']}",
            f"shadowy={params['shadowy']}",
            f"x={params['x_expr']}",
            f"y={config.position_y or params['y_expr']}",
            f"enable='between(t\\,{item.start_sec}\\,{item.end_sec})'",
        ]
        filters.append(":".join(parts))

    return ",".join(filters)


def build_cinematic_filter(width: int, height: int) -> str:
    """电影风额外滤镜：上下黑边"""
    bar_h = int(height * 0.08)
    return (
        f"drawbox=x=0:y=0:w={width}:h={bar_h}:color=black:t=fill,"
        f"drawbox=x=0:y={height - bar_h}:w={width}:h={bar_h}:color=black:t=fill"
    )


async def burn_captions(
    video_path: Path | str,
    output_path: Path | str,
    captions: list[str] | list[CaptionItem],
    style: CaptionStyle = "military",
    total_duration_sec: float | None = None,
    font_path: str = "",
) -> Path:
    """将字幕烧录到视频上

    Args:
        video_path: 输入视频
        output_path: 输出视频
        captions: 字幕文本列表或 CaptionItem 列表
        style: 字幕风格
        total_duration_sec: 视频总时长（当 captions 为 str 列表时必填）
    """
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not captions:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path), "-c", "copy", str(output_path)],
            check=True,
        )
        return output_path

    if isinstance(captions[0], str):
        if not total_duration_sec:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(video_path)],
                capture_output=True, text=True,
            )
            total_duration_sec = float(result.stdout.strip() or "10")
        items = from_captions_list(captions, total_duration_sec)
    else:
        items = captions

    config = CaptionConfig(items=items, style=style, font_path=font_path)
    vf = build_drawtext_filters(config)

    if style == "cinematic":
        bar_filter = build_cinematic_filter(1080, 1920)
        vf = f"{bar_filter},{vf}" if vf else bar_filter

    if not vf:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path), "-c", "copy", str(output_path)],
            check=True,
        )
        return output_path

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", vf,
        "-c:a", "copy",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"Captions burn failed: {stderr.decode()[-300:]}")

    logger.info("Captions burned: %s [style=%s, %d items]", output_path, style, len(items))
    return output_path


# ── ASS 字幕渲染（基于真实 word-level 时间戳，修复硬伤3）──

_ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},72,&H00FFFFFF,&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,1,5,1,2,10,10,80,134

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

_FONT_ASS = "Source Han Sans CN"
_FONT_ASS_FALLBACK = "Microsoft YaHei"
_TIMESTAMP_RESCALE_MIN_DIFF_MS = 300
_TIMESTAMP_RESCALE_MIN_RATIO = 0.05


def _ms_to_ass_time(ms: int) -> str:
    """毫秒 → ASS 时间格式 H:MM:SS.cs"""
    cs = (ms % 1000) // 10
    s = (ms // 1000) % 60
    m = (ms // 60000) % 60
    h = ms // 3600000
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _group_words_to_lines(
    word_timestamps: list,
    chars_per_line: int = 12,
    gap_threshold_ms: int = 500,
) -> list[tuple[str, int, int]]:
    """将 word_timestamps 合并成更自然的字幕事件 (text, start_ms, end_ms)。

    先按停顿和句读优先切成字幕事件，再在单个事件内部做最多两行的排版，
    避免一句中文被生硬拆成前后两张字幕卡。
    """
    if not word_timestamps:
        return []

    events: list[tuple[str, int, int]] = []
    buf_words: list = []
    buf_chars = 0
    max_event_chars = max(chars_per_line + 6, chars_per_line * 2 - 2)
    soft_break_punct = "，、：；,;:"
    hard_break_punct = "。！？!?~"

    for wt in word_timestamps:
        word = str(getattr(wt, "word", "") or "")
        if not word:
            continue

        if buf_words:
            gap = wt.start_ms - buf_words[-1].end_ms
            prev_text = "".join(str(getattr(x, "word", "") or "") for x in buf_words)
            prev_tail = prev_text[-1] if prev_text else ""
            force_break = False

            if gap >= gap_threshold_ms:
                force_break = True
            elif prev_tail in hard_break_punct:
                force_break = True
            elif prev_tail in soft_break_punct and buf_chars >= max(6, chars_per_line - 2):
                force_break = True
            elif buf_chars + len(word) > max_event_chars and (
                prev_tail in soft_break_punct or buf_chars >= chars_per_line
            ):
                force_break = True

            if force_break:
                text = _wrap_caption_event_text("".join(str(x.word or "") for x in buf_words), chars_per_line)
                events.append((text, buf_words[0].start_ms, buf_words[-1].end_ms))
                buf_words = []
                buf_chars = 0

        buf_words.append(wt)
        buf_chars += len(word)

    if buf_words:
        text = _wrap_caption_event_text("".join(str(x.word or "") for x in buf_words), chars_per_line)
        events.append((text, buf_words[0].start_ms, buf_words[-1].end_ms))

    return events


def _wrap_caption_event_text(text: str, chars_per_line: int = 12) -> str:
    """Wrap one subtitle event into at most two visual lines."""
    clean = re.sub(r"\s+", "", to_simplified_zh(str(text or "").strip()))
    if len(clean) <= chars_per_line:
        return clean

    max_total = chars_per_line * 2
    if len(clean) > max_total:
        clean = clean[:max_total]

    split = _find_balanced_split(clean, chars_per_line)
    if split <= 0 or split >= len(clean):
        return clean

    first = clean[:split].rstrip("，、：；,.!?！？")
    second = clean[split:].lstrip("，、：；,.!?！？")
    if not first or not second:
        return clean
    return f"{first}\\N{second}"


def _find_balanced_split(text: str, chars_per_line: int) -> int:
    preferred = "，、：；,;:"
    forbidden_end = set("的了呢吗呀啊吧着")
    forbidden_start = set("的了呢吗呀啊吧着就也还又把被并而且但")
    center = min(chars_per_line, max(1, len(text) // 2))
    candidates = []

    for idx, ch in enumerate(text[:-1], start=1):
        score = abs(idx - center)
        if idx > chars_per_line + 2:
            score += 100
        if ch in preferred:
            score -= 4
        prev_ch = text[idx - 1]
        next_ch = text[idx]
        if prev_ch in forbidden_end:
            score += 3
        if next_ch in forbidden_start:
            score += 3
        candidates.append((score, idx))

    if not candidates:
        return min(chars_per_line, len(text))

    best_idx = min(candidates)[1]
    if best_idx <= 0:
        return min(chars_per_line, len(text))
    return best_idx


def _detect_ass_font() -> str:
    try:
        import subprocess as sp
        result = sp.run(
            ["fc-list", ":lang=zh", "--format=%{family[0]}\n"],
            capture_output=True, text=True, timeout=3,
        )
        if _FONT_ASS in result.stdout:
            return _FONT_ASS
    except Exception:
        pass
    if Path("C:/Windows/Fonts/msyh.ttc").exists():
        return _FONT_ASS_FALLBACK
    return _FONT_ASS_FALLBACK


def _probe_media_duration_ms(media_path: Path | str) -> int:
    """Read the real media duration in milliseconds via ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(media_path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            return 0
        duration_sec = float((result.stdout or "").strip())
    except Exception as exc:
        logger.warning("probe media duration failed: %s", exc)
        return 0
    if duration_sec <= 0:
        return 0
    return int(duration_sec * 1000)


def _clone_word_timestamp(word_ts, start_ms: int, end_ms: int):
    cls = type(word_ts)
    try:
        return cls(word=word_ts.word, start_ms=start_ms, end_ms=end_ms)
    except Exception:
        clone = cls.__new__(cls)
        clone.word = word_ts.word
        clone.start_ms = start_ms
        clone.end_ms = end_ms
        return clone


def _retime_word_timestamps(
    word_timestamps: list,
    target_duration_ms: int,
    min_diff_ms: int = _TIMESTAMP_RESCALE_MIN_DIFF_MS,
    min_ratio: float = _TIMESTAMP_RESCALE_MIN_RATIO,
) -> list:
    """Rescale timestamps when TTS/ASR time axis drifts from the final media length."""
    if not word_timestamps or target_duration_ms <= 0:
        return word_timestamps

    source_end_ms = int(getattr(word_timestamps[-1], "end_ms", 0) or 0)
    if source_end_ms <= 0:
        return word_timestamps

    diff_ms = abs(target_duration_ms - source_end_ms)
    ratio = diff_ms / max(source_end_ms, 1)
    if diff_ms < min_diff_ms or ratio < min_ratio:
        return word_timestamps

    scale = target_duration_ms / source_end_ms
    retimed = []
    prev_end = 0
    for idx, item in enumerate(word_timestamps):
        start_raw = int(getattr(item, "start_ms", 0) or 0)
        end_raw = int(getattr(item, "end_ms", start_raw) or start_raw)
        new_start = max(0, int(round(start_raw * scale)))
        new_end = max(new_start, int(round(end_raw * scale)))
        if idx == len(word_timestamps) - 1:
            new_end = target_duration_ms
        if new_start < prev_end:
            new_start = prev_end
        if new_end < new_start:
            new_end = new_start
        retimed.append(_clone_word_timestamp(item, new_start, new_end))
        prev_end = new_end

    logger.info(
        "retimed subtitle timestamps: source=%dms target=%dms scale=%.4f words=%d",
        source_end_ms,
        target_duration_ms,
        scale,
        len(word_timestamps),
    )
    return retimed


def build_ass_content(
    word_timestamps: list,
    chars_per_line: int = 12,
) -> str:
    """从 word-level 时间戳生成 ASS 字幕文件内容。"""
    font = _detect_ass_font()
    header = _ASS_HEADER.format(font=font)

    lines = _group_words_to_lines(word_timestamps, chars_per_line=chars_per_line)
    events: list[str] = []
    for text, start_ms, end_ms in lines:
        text = to_simplified_zh(text)
        # 每行末尾延长 120ms 避免字幕闪烁消失
        end_ms_ext = end_ms + 120
        # \fad(80,60) = 80ms 渐入 + 60ms 渐出
        dialogue_text = r"{\fad(80,60)}" + text
        events.append(
            f"Dialogue: 0,{_ms_to_ass_time(start_ms)},{_ms_to_ass_time(end_ms_ext)},"
            f"Default,,0,0,0,,{dialogue_text}"
        )

    return header + "\n".join(events) + "\n"


async def burn_captions_from_word_timestamps(
    video_path: Path | str,
    output_path: Path | str,
    word_timestamps: list,
    chars_per_line: int = 12,
) -> Path:
    """基于真实 word-level 时间戳烧录 ASS 字幕（精准同步，修复硬伤3）。

    word_timestamps: 来自 voiceover.TTSResult.word_timestamps 或 Whisper 结果。
    """
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not word_timestamps:
        logger.warning("burn_captions_from_word_timestamps: 无时间戳，跳过字幕")
        import subprocess as sp
        sp.run(["ffmpeg", "-y", "-i", str(video_path), "-c", "copy", str(output_path)], check=True)
        return output_path

    probed_duration_ms = _probe_media_duration_ms(video_path)
    timed_words = _retime_word_timestamps(word_timestamps, probed_duration_ms)

    ass_content = build_ass_content(timed_words, chars_per_line=chars_per_line)

    ass_fd, ass_path = tempfile.mkstemp(suffix=".ass")
    try:
        with os.fdopen(ass_fd, "w", encoding="utf-8") as f:
            f.write(ass_content)

        # Windows 路径需要转为正斜杠并转义冒号，否则 FFmpeg ass filter 会报错
        ass_path_ffmpeg = ass_path.replace("\\", "/").replace(":", "\\:")

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", f"ass={ass_path_ffmpeg}",
            "-c:a", "copy",
            str(output_path),
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"ASS subtitle burn failed: {stderr.decode()[-400:]}")

    finally:
        try:
            os.unlink(ass_path)
        except OSError:
            pass

    logger.info(
        "ASS captions burned: %s [%d words → %d lines]",
        output_path,
        len(timed_words),
        len(_group_words_to_lines(timed_words, chars_per_line)),
    )
    return output_path
