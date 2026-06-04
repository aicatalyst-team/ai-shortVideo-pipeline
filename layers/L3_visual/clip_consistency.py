"""D41-B Chinese-CLIP image/prompt consistency scoring.

Model: OFA-Sys/chinese-clip-vit-base-patch16. It is lazy-loaded on first use
and cached process-wide. Any error returns None / passed=True so generation is
never blocked by the warning layer.
"""
from __future__ import annotations

import asyncio
import logging
import math

from pydantic import BaseModel

from config.settings import get_settings
from core.langfuse_client import observe

log = logging.getLogger(__name__)

_MODEL_ID = "OFA-Sys/chinese-clip-vit-base-patch16"
_model = None
_processor = None
_load_lock = asyncio.Lock()


class ClipConsistencyResult(BaseModel):
    image_path: str
    prompt: str
    score: float | None
    threshold: float
    passed: bool
    warning_message: str = ""


async def _ensure_model_loaded() -> bool:
    """Lazy-load Chinese-CLIP and return True when ready."""
    global _model, _processor
    if _model is not None and _processor is not None:
        return True
    async with _load_lock:
        if _model is not None and _processor is not None:
            return True
        try:
            from transformers import ChineseCLIPModel, ChineseCLIPProcessor

            _processor = ChineseCLIPProcessor.from_pretrained(_MODEL_ID)
            _model = ChineseCLIPModel.from_pretrained(_MODEL_ID).eval()
            log.info("[clip] chinese-clip loaded model_id=%s", _MODEL_ID)
            return True
        except Exception as exc:
            log.warning("[clip] model load failed, scoring disabled: %s", exc)
            _model = None
            _processor = None
            return False


def _score_sync(image_path: str, prompt: str) -> float | None:
    """Synchronous inference; run via asyncio.to_thread."""
    try:
        from PIL import Image
        import torch

        image = Image.open(image_path).convert("RGB")
        inputs = _processor(text=[prompt], images=image, return_tensors="pt", padding=True)
        with torch.no_grad():
            outputs = _model(**inputs)
            score = outputs.logits_per_image.item()
            normalized = 1.0 / (1.0 + math.exp(-(score - 18) / 4))
            return float(normalized)
    except Exception as exc:
        log.warning("[clip] scoring failed for %s: %s", image_path, exc)
        return None


async def score_image_prompt(image_path: str, prompt: str) -> float | None:
    """Return 0-1 consistency score, or None when unavailable."""
    if not image_path or not prompt:
        return None
    if not await _ensure_model_loaded():
        return None
    try:
        return await asyncio.to_thread(_score_sync, image_path, prompt)
    except Exception as exc:
        log.warning("[clip] scoring thread failed for %s: %s", image_path, exc)
        return None


@observe(name="clip_consistency", as_type="span")
async def check_consistency(
    image_path: str,
    prompt: str,
    threshold: float | None = None,
    storyboard_id: str | None = None,
    clip_no: int | None = None,
) -> ClipConsistencyResult:
    """Score one generated keyframe and add best-effort Langfuse metadata."""
    cfg = get_settings()
    threshold = threshold if threshold is not None else cfg.clip_consistency_threshold
    score = await score_image_prompt(image_path, prompt)
    passed = score is None or score >= threshold
    log.info(
        "[clip] clip_no=%s score=%s threshold=%.3f passed=%s",
        clip_no,
        f"{score:.3f}" if score is not None else "None",
        threshold,
        passed,
    )
    warning_message = ""
    if score is not None and not passed:
        warning_message = (
            f"📉 CLIP 一致性 {score:.3f} < {threshold:.3f}，"
            f"第 {clip_no or '?'} 段关键帧可能跑题"
        )
        log.warning("[clip] %s prompt=%s", warning_message, prompt[:80])

    try:
        from langfuse.decorators import langfuse_context

        langfuse_context.update_current_observation(
            metadata={
                "clip_score": score,
                "clip_threshold": threshold,
                "clip_passed": passed,
                "storyboard_id": storyboard_id,
                "clip_no": clip_no,
            }
        )
    except Exception:
        pass

    return ClipConsistencyResult(
        image_path=image_path,
        prompt=prompt,
        score=score,
        threshold=threshold,
        passed=passed,
        warning_message=warning_message,
    )
