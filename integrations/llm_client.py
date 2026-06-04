from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path

import httpx
from openai import AsyncOpenAI
from zhipuai import ZhipuAI

from config.settings import get_settings

log = logging.getLogger(__name__)

_deepseek: AsyncOpenAI | None = None
_glm: ZhipuAI | None = None

# GLM-4V 视觉模型默认 ID（支持图片理解）。
# 实际调用优先读取 settings.glm_vision_model，便于线上切模型排查用量。
GLM4V_MODEL = "glm-4v"


def get_deepseek() -> AsyncOpenAI:
    global _deepseek
    if _deepseek is None:
        cfg = get_settings()
        _deepseek = AsyncOpenAI(api_key=cfg.deepseek_api_key, base_url=cfg.deepseek_base_url)
    return _deepseek


def get_glm() -> ZhipuAI:
    global _glm
    if _glm is None:
        cfg = get_settings()
        _glm = ZhipuAI(api_key=cfg.glm_api_key)
    return _glm


async def call_deepseek(system: str, user: str, temperature: float = 0.7) -> str:
    cfg = get_settings()
    client = get_deepseek()
    response = await client.chat.completions.create(
        model=cfg.deepseek_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
    )
    return response.choices[0].message.content or ""


def _image_to_data_url(image_path: Path) -> str:
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    suffix = image_path.suffix.lower().lstrip(".")
    mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
    return f"data:image/{mime};base64,{b64}"


def _extract_message_content(message: object) -> str:
    content = getattr(message, "content", "") or ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
            else:
                text = getattr(item, "text", None)
                if text:
                    parts.append(str(text))
        return "\n".join(parts)
    return str(content)


def _log_empty_glm4v_response(response: object, model: str) -> None:
    try:
        if hasattr(response, "model_dump"):
            data = response.model_dump()
        elif hasattr(response, "dict"):
            data = response.dict()
        else:
            data = {"repr": repr(response)}
        for key in ("request_id", "task_id"):
            data.pop(key, None)
        safe = json.dumps(data, ensure_ascii=False, default=str)[:2000]
    except Exception as exc:
        safe = f"<failed to serialize response: {exc}>"
    log.warning("[GLM-4V] 返回空内容，model=%s, response=%s", model, safe)


def _call_glm4v_api(image_path: Path, prompt: str) -> str:
    """直接调用 GLM-4V API（单张图片），不经过任何包装层。"""
    client = get_glm()
    cfg = get_settings()
    data_url = _image_to_data_url(image_path)
    model = cfg.glm_vision_model or GLM4V_MODEL
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    message = response.choices[0].message
    content = _extract_message_content(message)
    if not content.strip():
        _log_empty_glm4v_response(response, model)
    return content


def call_glm4v(image_path: str | Path, prompt: str) -> str:
    """GLM-4V 分析单张图片。"""
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"GLM-4V 图片不存在: {path}")
    log.info("[GLM-4V] 单图分析: %s, prompt=%s...", path.name, prompt[:40])
    return _call_glm4v_api(path, prompt)


def _make_frame_grid(image_paths: list[Path], cols: int = 3) -> Path:
    """把多帧拼成一张网格图（左→右、上→下即时间顺序），写入临时文件返回路径。

    GLM-4V 单次只接受一张图，网格图是让模型看到完整视频叙事的最可靠方式。
    每帧左上角标注序号，方便模型理解时间顺序。
    """
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    rows = (len(image_paths) + cols - 1) // cols
    with Image.open(image_paths[0]) as first:
        first_w, first_h = first.size
    if first_h > first_w:
        thumb_w, thumb_h = 360, 640  # 竖屏视频保持 9:16，不要压扁成横图
    else:
        thumb_w, thumb_h = 480, 270  # 横屏/方图使用 16:9 缩略格

    grid = Image.new("RGB", (thumb_w * cols, thumb_h * rows), color=(20, 20, 20))
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 24)
    except Exception:
        font = ImageFont.load_default()

    for idx, p in enumerate(image_paths):
        r, c = divmod(idx, cols)
        frame = Image.open(p).convert("RGB")
        frame = ImageOps.contain(frame, (thumb_w, thumb_h))
        x0 = c * thumb_w + (thumb_w - frame.width) // 2
        y0 = r * thumb_h + (thumb_h - frame.height) // 2
        grid.paste(frame, (x0, y0))
        draw = ImageDraw.Draw(grid)
        draw.rectangle([(c * thumb_w, r * thumb_h), (c * thumb_w + 38, r * thumb_h + 30)],
                       fill=(0, 0, 0, 180))
        draw.text((c * thumb_w + 4, r * thumb_h + 3), f"#{idx + 1}", fill="yellow", font=font)

    import tempfile
    tmp = Path(tempfile.mktemp(suffix="_grid.jpg"))
    grid.save(tmp, "JPEG", quality=85)
    log.info("[GLM-4V] 网格图生成: %dx%d, %d帧 → %s", cols, rows, len(image_paths), tmp.name)
    return tmp


def call_glm4v_multi(image_paths: list[str | Path], prompt: str) -> str:
    """GLM-4V 多帧分析：将多帧拼成网格图后作为单张图发给模型。

    GLM-4V 单次只支持 1 张图；网格图让模型同时看到所有帧的时间序列。
    image_paths: 按时间顺序排列的帧图路径（建议 4-8 帧）。
    """
    paths = [Path(p) for p in image_paths]
    missing = [p for p in paths if not p.is_file()]
    if missing:
        raise FileNotFoundError(f"GLM-4V 帧图不存在: {[str(p) for p in missing]}")

    log.info("[GLM-4V] 多帧→网格分析: %d 帧, prompt=%s...", len(paths), prompt[:40])

    grid_path = _make_frame_grid(paths)
    try:
        grid_prompt = (
            f"{prompt}\n\n"
            f"【网格图说明】图片由 {len(paths)} 帧按时间顺序拼成，"
            f"从左到右、从上到下为时间顺序，每帧左上角有序号 #1~#{len(paths)}。"
            "请基于所有帧的完整序列完成上面的任务。"
        )
        result = _call_glm4v_api(grid_path, grid_prompt)
    finally:
        try:
            grid_path.unlink()
        except OSError:
            pass

    log.info("[GLM-4V] 多帧分析返回%d字", len(result))
    return result


# ─────── 通过 Java gateway 走 multi-provider failover ───────

GATEWAY_INTERNAL_BASE = os.getenv("GATEWAY_INTERNAL_BASE", "http://gateway:8080")


async def call_via_gateway(
    system: str,
    user: str,
    *,
    biz_type: str = "creative",
    tenant_id: str = "default",
    project_id: str | None = None,
    node_id: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    model: str | None = None,
) -> str:
    """通过 Java gateway 调 LLM，获得多模型 failover + fallback_chain 落库。"""
    payload: dict[str, object] = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "biz_type": biz_type,
        "tenant_id": tenant_id,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if project_id:
        payload["project_id"] = project_id
    if node_id:
        payload["node_id"] = node_id
    if model:
        payload["model"] = model

    async with httpx.AsyncClient(timeout=90.0) as client:
        try:
            resp = await client.post(
                f"{GATEWAY_INTERNAL_BASE}/internal/llm/chat",
                json=payload,
            )
            data = resp.json()
            if resp.status_code != 200:
                log.warning(
                    "[llm-gateway] failed status=%s error=%s chain=%s",
                    resp.status_code,
                    data.get("error"),
                    data.get("fallback_chain"),
                )
                raise RuntimeError(
                    f"gateway llm failed: {data.get('error')} -- {data.get('message')}"
                )

            chain = data.get("fallback_chain", [])
            if len(chain) > 1:
                log.info(
                    "[llm-gateway] fallback success provider=%s chain_len=%d chain=%s",
                    data.get("provider"),
                    len(chain),
                    [f"{c.get('provider')}:{c.get('status')}" for c in chain],
                )
            return data.get("content", "")
        except httpx.RequestError as exc:
            log.error("[llm-gateway] network error: %s", exc)
            log.warning("[llm-gateway] falling back to direct deepseek")
            return await call_deepseek(system, user, temperature=temperature)


def is_gateway_enabled() -> bool:
    """是否启用 gateway LLM 路由。"""
    return os.getenv("LLM_USE_GATEWAY", "1") == "1"
