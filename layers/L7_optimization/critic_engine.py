"""Sprint 3 VL critic for finished videos.

The existing quality gate scores text and image prompts before publishing. This
module looks at actual video frames with a vision model, then returns a compact
quality verdict and regeneration recommendation. It is intentionally small:
one VL call per video, no multi-round loops by default.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from core.parsers import parse_json_object
from integrations.llm_client import call_glm4v_multi

log = logging.getLogger(__name__)

VL_CRITIC_PASS_THRESHOLD = 70
DEFAULT_VL_CRITIC_COST_RMB = 0.25
MAX_REGEN_ATTEMPTS = 1

DIM_KEYS = [
    "character_consistency",
    "visual_realism",
    "shot_diversity",
    "caption_sync",
    "publish_readiness",
]

DIM_WEIGHTS = {
    "character_consistency": 0.22,
    "visual_realism": 0.26,
    "shot_diversity": 0.20,
    "caption_sync": 0.16,
    "publish_readiness": 0.16,
}


@dataclass
class VLCriticScore:
    total: float
    passed: bool
    dimensions: dict[str, float] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    should_regenerate: bool = False
    valid: bool = True
    error: str = ""
    estimated_cost_rmb: float = DEFAULT_VL_CRITIC_COST_RMB
    frames_analyzed: int = 0
    raw: str = ""


def _clamp_score(value: object, default: float = 60.0) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = default
    return max(0.0, min(100.0, score))


def _parse_score(value: object) -> float | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, score))


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "需要", "是"}
    return False


def _as_text_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _invalid_score(*, frames_analyzed: int, raw: str, error: str) -> VLCriticScore:
    return VLCriticScore(
        total=0,
        passed=False,
        dimensions={},
        issues=[error],
        suggestions=[
            "检查 GLM 视觉模型返回结构与服务端日志；本次不要按 60 分真实质量分处理。",
        ],
        should_regenerate=False,
        valid=False,
        error=error,
        frames_analyzed=frames_analyzed,
        raw=raw,
    )


def _build_vl_prompt(
    *,
    narration: str,
    style_name: str,
    caption_sample: str,
    strict: bool = False,
) -> str:
    if strict:
        return (
            "Return ONLY one valid JSON object. Your response MUST start with { and end with }. "
            "Do NOT describe the image. Do NOT transcribe/OCR subtitles or on-screen text. "
            "Do NOT output '<|observation|>' or any natural language. "
            "You are a visual quality critic for a Chinese vertical short video. "
            "You are looking at an ordered grid of keyframes from the final rendered video. "
            "All five score fields MUST be numbers from 0 to 100. "
            'Schema: {"character_consistency":75,"visual_realism":70,'
            '"shot_diversity":80,"caption_sync":75,"publish_readiness":72,'
            '"issues":["short Chinese issue"],"suggestions":["short Chinese fix"],'
            '"should_regenerate":false}. '
            "Score character consistency, visual realism, shot variety, subtitle/caption readability/sync, "
            "and overall publish readiness. "
            f"Style: {style_name or 'unknown'}. "
            f"Narration summary: {narration[:500]}. "
            f"Caption sample: {caption_sample[:250]}."
        )

    return (
        "只输出一个合法 JSON 对象。回复必须以 { 开头，以 } 结尾。\n"
        "禁止描述图片，禁止 OCR/复述画面字幕，禁止输出解释文字。\n"
        "你是短视频成片质检专家。请基于这些按时间顺序排列的关键帧，"
        "评估这条中文图文混剪/解说类短视频是否达到可发布标准。\n\n"
        "评分维度每项 0-100：\n"
        "1. character_consistency: 角色/人物/主体是否前后一致，有无穿帮\n"
        "2. visual_realism: 画面真实感，是否一眼AI、塑料感、过度美颜\n"
        "3. shot_diversity: 镜头/构图/景别是否多样，是否一镜到底\n"
        "4. caption_sync: 从画面字幕状态推断字幕节奏是否自然，有无明显遮挡/错位\n"
        "5. publish_readiness: 综合可发布程度\n\n"
        "只输出 JSON，不要代码围栏，不要解释：\n"
        "{\n"
        '  "character_consistency": 75,\n'
        '  "visual_realism": 70,\n'
        '  "shot_diversity": 80,\n'
        '  "caption_sync": 75,\n'
        '  "publish_readiness": 72,\n'
        '  "issues": ["最主要问题"],\n'
        '  "suggestions": ["下一次重生应如何修"],\n'
        '  "should_regenerate": false\n'
        "}\n\n"
        f"垂类: {style_name or 'unknown'}\n"
        f"解说稿摘要: {narration[:600]}\n"
        f"字幕样例: {caption_sample[:300]}"
    )


def _parse_vl_score(raw: str, *, frames_analyzed: int, regen_attempt: int) -> tuple[VLCriticScore | None, str]:
    if not raw.strip():
        return None, "GLM-4V 未返回任何文本内容"

    data = parse_json_object(raw)
    missing = [k for k in DIM_KEYS if k not in data]
    if missing:
        return None, f"GLM-4V 未返回有效评分 JSON，缺少字段: {', '.join(missing)}"

    dimensions: dict[str, float] = {}
    non_numeric: list[str] = []
    for key in DIM_KEYS:
        score = _parse_score(data.get(key))
        if score is None:
            non_numeric.append(key)
        else:
            dimensions[key] = score
    if non_numeric:
        return None, f"GLM-4V 评分字段不是数字: {', '.join(non_numeric)}"

    total = sum(dimensions[k] * DIM_WEIGHTS[k] for k in DIM_KEYS)
    issues = _as_text_list(data.get("issues"))
    suggestions = _as_text_list(data.get("suggestions"))
    passed = total >= VL_CRITIC_PASS_THRESHOLD
    model_regen = _as_bool(data.get("should_regenerate"))
    should_regenerate = (not passed or model_regen) and regen_attempt < MAX_REGEN_ATTEMPTS

    return VLCriticScore(
        total=round(total, 1),
        passed=passed,
        dimensions=dimensions,
        issues=issues,
        suggestions=suggestions,
        should_regenerate=should_regenerate,
        frames_analyzed=frames_analyzed,
        raw=raw,
    ), ""


def extract_video_keyframes(video_path: str | Path, frame_count: int = 6) -> list[Path]:
    """Extract evenly sampled frames into a temporary directory."""
    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"视频文件不存在: {path}")

    tmp_dir = Path(tempfile.mkdtemp(prefix="vl_critic_"))
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        duration = max(1.0, float((probe.stdout or "0").strip()))
    except ValueError:
        duration = float(frame_count)

    timestamps = [
        min(duration - 0.1, max(0.0, duration * (i + 0.5) / frame_count))
        for i in range(frame_count)
    ]
    frames: list[Path] = []
    for idx, ts in enumerate(timestamps, start=1):
        out = tmp_dir / f"frame_{idx:02d}.jpg"
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{ts:.2f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "scale=640:-1",
            "-q:v",
            "3",
            str(out),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0 and out.exists():
            frames.append(out)

    if not frames:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError("抽帧失败: 未生成关键帧")

    return frames


def score_video_with_vl(
    video_path: str | Path,
    *,
    narration: str = "",
    style_name: str = "",
    caption_sample: str = "",
    frame_count: int = 6,
    regen_attempt: int = 0,
) -> VLCriticScore:
    """Score a finished video by sending sampled frames to GLM-4V."""
    frames: list[Path] = []
    try:
        frames = extract_video_keyframes(video_path, frame_count=frame_count)
        last_raw = ""
        last_error = ""
        for attempt, strict in enumerate((False, True), start=1):
            prompt = _build_vl_prompt(
                narration=narration,
                style_name=style_name,
                caption_sample=caption_sample,
                strict=strict,
            )
            raw = call_glm4v_multi(frames, prompt)
            last_raw = raw
            score, error = _parse_vl_score(raw, frames_analyzed=len(frames), regen_attempt=regen_attempt)
            if score is not None:
                if attempt > 1:
                    log.info("[VL Critic] retry succeeded with strict JSON prompt")
                return score
            last_error = error
            log.warning(
                "[VL Critic] GLM-4V score parse failed attempt=%d strict=%s error=%s raw=%r",
                attempt,
                strict,
                error,
                raw[:500],
            )

        return _invalid_score(frames_analyzed=len(frames), raw=last_raw, error=last_error)
    finally:
        if frames:
            shutil.rmtree(frames[0].parent, ignore_errors=True)


def format_vl_critic_report(score: VLCriticScore) -> str:
    if not score.valid:
        lines = [
            f"VL 成片质检未完成（已看 {score.frames_analyzed} 帧，约 ¥{score.estimated_cost_rmb:.2f}）",
            f"原因：{score.error or '模型返回无效'}",
        ]
        if score.suggestions:
            lines.append("排查建议:")
            lines.extend(f"  - {item}" for item in score.suggestions[:4])
        return "\n".join(lines)

    status = "通过" if score.passed else "未达标"
    lines = [
        f"VL 成片质检：{score.total:.0f}/100（{status}，已看 {score.frames_analyzed} 帧，约 ¥{score.estimated_cost_rmb:.2f}）"
    ]
    labels = {
        "character_consistency": "角色一致",
        "visual_realism": "真实感",
        "shot_diversity": "镜头变化",
        "caption_sync": "字幕观感",
        "publish_readiness": "发布准备",
    }
    for key, label in labels.items():
        if key in score.dimensions:
            lines.append(f"  {label}: {score.dimensions[key]:.0f}")
    if score.issues:
        lines.append("主要问题:")
        lines.extend(f"  - {item}" for item in score.issues[:4])
    if score.suggestions:
        lines.append("修复建议:")
        lines.extend(f"  - {item}" for item in score.suggestions[:4])
    if score.should_regenerate:
        lines.append("建议：允许最多 1 次重生成，本次已标记为需要重生。")
    return "\n".join(lines)


def should_regenerate(score: VLCriticScore, attempt: int = 0) -> bool:
    return score.should_regenerate and attempt < MAX_REGEN_ATTEMPTS
