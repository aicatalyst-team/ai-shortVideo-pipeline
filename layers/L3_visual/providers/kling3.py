"""Phase P Sprint P11: Kling 3.0 Native Audio PoC provider.

This module is an evaluation stub, not a replacement for the existing
stitched_i2v pipeline in kling_v3.py. It is only enabled by
settings.visual_generation_mode='kling3_native_audio' and raises explicit
errors when the assumed Kling 3.0 API is unavailable.

Research assumptions as of 2026-05, pending user verification:
- API base URL: settings.kling3_base_url, defaulting to settings.kling_base_url
- Path: /v1/videos/text2video_v3
- Model: kling-v3.0
- Native audio params: enable_native_audio + narration
- Duration: 3-15s, assumed 1s step
- Pricing: unpublished; PoC must collect real costs before any product decision

Public references:
- Kuaishou investor release mentioning Kling 3.0 model family
- https://klingapi.com/models/kling-3-0
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from dataclasses import dataclass

import httpx
import jwt

from config.settings import get_settings
from layers.L3_visual.providers.base import VideoResult

log = logging.getLogger(__name__)

KLING3_MIN_DURATION_SEC: int = 3
KLING3_MAX_DURATION_SEC: int = 15
KLING3_DURATION_STEP_SEC: int = 1


class Kling3NotAvailableError(RuntimeError):
    """Kling 3.0 API is unavailable, not GA, unauthorized, or unreachable."""


class Kling3FeatureUnsupportedError(RuntimeError):
    """Kling 3.0 accepted the endpoint but does not support a requested feature."""


@dataclass
class Kling3Request:
    """Single Kling 3.0 native-audio generation request."""

    image_path: str | None
    narration: str
    visual_prompt: str
    duration_sec: int
    aspect_ratio: str = "9:16"
    character_ref_path: str | None = None
    enable_native_audio: bool = True
    voice_id: str = "default_zh_female"
    style_intensity: str = "标准增强"


@dataclass
class Kling3Result:
    """Kling 3.0 result; the video is expected to include synchronized audio."""

    video: VideoResult
    audio_included: bool
    audio_duration_sec: float
    actual_duration_sec: float
    task_id: str
    raw_response: dict


def kling3_bearer_token() -> str:
    """Sign a bearer token, assuming Kling 3.0 auth matches the existing API."""
    cfg = get_settings()
    now = int(time.time())
    ak = getattr(cfg, "kling3_access_key", "") or cfg.kling_access_key
    sk = getattr(cfg, "kling3_secret_key", "") or cfg.kling_secret_key
    payload = {"iss": ak, "exp": now + 1800, "nbf": now - 5}
    return jwt.encode(payload, sk, algorithm="HS256", headers={"alg": "HS256", "typ": "JWT"})


def kling3_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {kling3_bearer_token()}"}


def _clamp_duration(duration_sec: int | None) -> int:
    """Clamp duration to the assumed Kling 3.0 [3, 15]s range."""
    d = max(KLING3_MIN_DURATION_SEC, min(KLING3_MAX_DURATION_SEC, int(duration_sec or 5)))
    if KLING3_DURATION_STEP_SEC > 1:
        d = (d // KLING3_DURATION_STEP_SEC) * KLING3_DURATION_STEP_SEC
    return d


async def generate_native_audio_video(
    request: Kling3Request,
    *,
    output_path: str,
    timeout_sec: int = 600,
    poll_interval_sec: int = 5,
) -> Kling3Result:
    """Generate one video with native audio and download it to output_path."""
    cfg = get_settings()
    base_url = (getattr(cfg, "kling3_base_url", "") or cfg.kling_base_url).rstrip("/")
    model_name = getattr(cfg, "kling3_model", "") or "kling-v3.0"
    duration = _clamp_duration(request.duration_sec)

    payload: dict = {
        "model_name": model_name,
        "prompt": request.visual_prompt,
        "narration": request.narration,
        "duration": str(duration),
        "aspect_ratio": request.aspect_ratio,
        "enable_native_audio": request.enable_native_audio,
        "voice_id": request.voice_id,
    }

    if request.image_path and os.path.isfile(request.image_path):
        with open(request.image_path, "rb") as f:
            payload["image"] = base64.b64encode(f.read()).decode()
    if request.character_ref_path and os.path.isfile(request.character_ref_path):
        with open(request.character_ref_path, "rb") as f:
            payload["character_ref"] = base64.b64encode(f.read()).decode()

    log.info(
        "[Kling3] submit model=%s duration=%ds aspect=%s native_audio=%s narration=%d chars prompt=%s...",
        model_name,
        duration,
        request.aspect_ratio,
        request.enable_native_audio,
        len(request.narration or ""),
        (request.visual_prompt or "")[:60],
    )

    submit_url = f"{base_url}/v1/videos/text2video_v3"
    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        try:
            resp = await client.post(submit_url, headers=kling3_headers(), json=payload)
        except httpx.HTTPError as exc:
            raise Kling3NotAvailableError(f"Kling 3.0 submit network failed: {exc}") from exc

        try:
            resp_data = resp.json()
        except ValueError as exc:
            raise Kling3NotAvailableError(f"Kling 3.0 non-JSON response: {resp.text[:200]}") from exc

        code = resp_data.get("code")
        message = resp_data.get("message", "")
        if code != 0:
            if code in (404, 4040, 4001):
                raise Kling3NotAvailableError(
                    f"Kling 3.0 model unavailable or endpoint invalid (code={code} msg={message})"
                )
            if "native_audio" in message.lower() or "audio" in message.lower():
                raise Kling3FeatureUnsupportedError(
                    f"Kling 3.0 native_audio unavailable (code={code} msg={message})"
                )
            raise RuntimeError(f"Kling 3.0 submit failed code={code} msg={message}")

        task_id = resp_data.get("data", {}).get("task_id")
        if not task_id:
            raise Kling3NotAvailableError(f"Kling 3.0 response missing task_id: {resp_data}")

        poll_url = f"{base_url}/v1/videos/text2video_v3/{task_id}"
        elapsed = 0
        delay = poll_interval_sec
        while elapsed < timeout_sec:
            await asyncio.sleep(delay)
            elapsed += delay
            try:
                poll_resp = await client.get(poll_url, headers=kling3_headers())
                poll_data = poll_resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("[Kling3] poll transient error elapsed=%ds: %s", elapsed, exc)
                continue

            data = poll_data.get("data", {})
            status = data.get("task_status", "")
            if status == "succeed":
                videos = data.get("task_result", {}).get("videos", [])
                if not videos:
                    raise RuntimeError("Kling 3.0 succeeded but videos is empty")
                meta = videos[0]
                video_url = meta.get("url", "")
                if not video_url:
                    raise RuntimeError("Kling 3.0 video result missing url")

                os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
                dl_resp = await client.get(video_url)
                dl_resp.raise_for_status()
                with open(output_path, "wb") as f:
                    f.write(dl_resp.content)

                actual_duration = float(meta.get("duration", duration))
                return Kling3Result(
                    video=VideoResult(
                        url=video_url,
                        local_path=output_path,
                        duration_sec=actual_duration,
                        task_id=task_id,
                        model=model_name,
                    ),
                    audio_included=bool(meta.get("has_audio", request.enable_native_audio)),
                    audio_duration_sec=float(meta.get("audio_duration", 0)),
                    actual_duration_sec=actual_duration,
                    task_id=task_id,
                    raw_response=poll_data,
                )
            if status == "failed":
                err = data.get("task_status_msg", "unknown failure")
                raise RuntimeError(f"Kling 3.0 task failed task_id={task_id} msg={err}")

            delay = min(int(delay * 1.4), 30)

        raise RuntimeError(f"Kling 3.0 task timeout ({timeout_sec}s) task_id={task_id}")


def is_kling3_enabled() -> bool:
    """Return True only when the explicit PoC mode is selected."""
    cfg = get_settings()
    return getattr(cfg, "visual_generation_mode", "stitched_i2v") == "kling3_native_audio"
