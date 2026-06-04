"""Phase P Sprint P4：clip 成本估算（用于审核消息展示）。"""
from __future__ import annotations

_KLING_PRICE_PER_SEC: dict[str, dict[str, float]] = {
    "kling-v2-5-turbo": {"standard": 0.10, "pro": 0.20},
    "kling-v2-1": {"standard": 0.08, "pro": 0.16},
    "kling-v1-6": {"standard": 0.07, "pro": 0.14},
}

_TEXT_TO_IMAGE_PRICE: float = 0.10
_TTS_PRICE_PER_K_CHAR: float = 0.30


def estimate_clip_cost(
    model: str,
    duration_sec: int | float,
    quality: str = "standard",
    *,
    include_first_frame: bool = True,
    narration_char_count: int = 0,
) -> float:
    """估算单个 clip 总成本（元）。"""
    model_prices = _KLING_PRICE_PER_SEC.get(model, _KLING_PRICE_PER_SEC["kling-v2-5-turbo"])
    per_sec = model_prices.get(quality, model_prices["standard"])
    video_cost = per_sec * float(duration_sec)
    first_frame_cost = _TEXT_TO_IMAGE_PRICE if include_first_frame else 0.0
    tts_cost = (narration_char_count / 1000.0) * _TTS_PRICE_PER_K_CHAR
    return round(video_cost + first_frame_cost + tts_cost, 2)


def estimate_clips_total_cost(
    clips: list[dict],
    *,
    model: str = "kling-v2-5-turbo",
    quality: str = "standard",
) -> float:
    """批量算 list of enriched_clips 的总成本。"""
    total = 0.0
    for clip in clips:
        narration = clip.get("narration_segment", "") or ""
        total += estimate_clip_cost(
            model=model,
            duration_sec=clip.get("duration_sec", 5),
            quality=quality,
            include_first_frame=True,
            narration_char_count=len(narration.strip()),
        )
    return round(total, 2)
