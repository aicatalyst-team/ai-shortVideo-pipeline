from __future__ import annotations

import asyncio
import base64
import logging
import os
import time

import httpx
import jwt

from config.settings import get_settings
from layers.L3_visual.providers.base import VideoResult

log = logging.getLogger(__name__)

MODE_MAP = {
    "standard": "std",
    "pro": "pro",
}


def kling_bearer_token() -> str:
    cfg = get_settings()
    now = int(time.time())
    payload = {"iss": cfg.kling_access_key, "exp": now + 1800, "nbf": now - 5}
    return jwt.encode(payload, cfg.kling_secret_key, algorithm="HS256", headers={"alg": "HS256", "typ": "JWT"})


def kling_image_bearer_token() -> str:
    cfg = get_settings()
    ak = cfg.kling_image_access_key or cfg.kling_access_key
    sk = cfg.kling_image_secret_key or cfg.kling_secret_key
    now = int(time.time())
    payload = {"iss": ak, "exp": now + 1800, "nbf": now - 5}
    return jwt.encode(payload, sk, algorithm="HS256", headers={"alg": "HS256", "typ": "JWT"})


def kling_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {kling_bearer_token()}"}


def kling_image_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {kling_image_bearer_token()}"}


# 可灵 v2+ API 接受的 camera_control.type（5 种）
#  simple              — 用户自定义六轴运动，config 六个字段
#  down_back           — 预设：下移并后退
#  forward_up          — 预设：前进并上仰
#  right_turn_forward  — 预设：右旋并前进
#  left_turn_forward   — 预设：左旋并前进
KLING_V2_NATIVE_TYPES = {
    "simple", "down_back", "forward_up", "right_turn_forward", "left_turn_forward"
}

# / Sprint P0：可灵某些模型整字段不支持 camera_control（不只是 type 弃用）
# 实测 kling-v2-5-turbo 传任何 camera_control 都报 1201 "Camera control is not supported by the current model"
# 这里维护已知黑名单，命中模型直接跳过 camera_control，省 30s/段 + 1 次 API 调用
# TODO（P3 之后）：迁到 settings.kling_camera_control_blacklist，从 .env 配
MODELS_WITHOUT_CAMERA_CONTROL: set[str] = {
    "kling-v2-5-turbo",
}

# 旧 type → simple 六轴映射（部署日真修，可灵 v2+ 已弃用旧枚举）
# config 字段：horizontal/vertical/pan/tilt/roll/zoom 各 [-10, 10]
#  horizontal = 水平位移（左负右正）
#  vertical   = 垂直位移（下负上正）
#  pan        = 水平旋转
#  tilt       = 垂直旋转
#  roll       = 翻滚
#  zoom       = 焦距推拉（正=推近 / 负=拉远）
_LEGACY_TYPE_TO_SIMPLE_CONFIG = {
    "push_in":   lambda c: {"zoom": abs(_safe_num(c.get("zoom"), 5))},
    "pull_out":  lambda c: {"zoom": -abs(_safe_num(c.get("zoom"), 5))},
    "pan_left":  lambda c: {"horizontal": -abs(_safe_num(c.get("horizontal") or c.get("pan"), 5))},
    "pan_right": lambda c: {"horizontal":  abs(_safe_num(c.get("horizontal") or c.get("pan"), 5))},
    "tilt_up":   lambda c: {"vertical":    abs(_safe_num(c.get("vertical") or c.get("tilt"), 5))},
    "tilt_down": lambda c: {"vertical":   -abs(_safe_num(c.get("vertical") or c.get("tilt"), 5))},
    "orbit":     lambda c: {"pan": abs(_safe_num(c.get("zoom"), 5)),
                            "horizontal": abs(_safe_num(c.get("zoom"), 5))},
    "static":    lambda c: None,  # 不传 camera_control（可灵默认就是固定机位）
}


def _safe_num(v, default: float) -> float:
    """把 yaml/json 里可能是 None/字符串/数字的值规整到 [-10, 10]。"""
    try:
        n = float(v)
    except (TypeError, ValueError):
        n = float(default)
    return max(-10.0, min(10.0, n))


def normalize_camera_control(camera_control: dict | None) -> dict | None:
    """把旧 type 映射到可灵 v2+ 接受的 simple+config；不能映射的返回 None。

    透传规则：
      - None / 空 → 返回 None
      - 已是 v2 原生 type → 透传
      - 旧 type 在映射表 → 转 simple+config
      - 旧 type=static → 返回 None（让可灵走默认）
      - 未知 type → 返回 None + log warning
    """
    if not camera_control:
        return None
    t = camera_control.get("type")
    if t in KLING_V2_NATIVE_TYPES:
        return camera_control

    mapper = _LEGACY_TYPE_TO_SIMPLE_CONFIG.get(t)
    if mapper is None:
        log.warning("[Kling] 未知 camera_control.type=%r，去掉 camera_control 走默认机位", t)
        return None

    cfg = camera_control.get("config") or {}
    simple_cfg = mapper(cfg)
    if simple_cfg is None:
        # static → 不传
        return None
    return {"type": "simple", "config": simple_cfg}


async def image_to_video(
    image_path: str,
    prompt: str,
    output_path: str,
    duration_sec: int = 5,
    aspect_ratio: str = "9:16",
    quality: str = "standard",
    character_ref_path: str | None = None,
    camera_control: dict | None = None,
) -> VideoResult:
    """
    调用可灵图生视频 API。
    可灵 duration 只接受 5 或 10，自动对齐。
    当传入 character_ref_path 时，注入角色参考以保持视频内角色一致性。

    camera_control: 镜头控制参数，如
        {"type": "push_in", "config": {"horizontal": 0, "vertical": 0, "zoom": 5}}
        type 见 CAMERA_CONTROL_TYPES，config 各轴范围 [-10, 10]。
        传 None 则不控制镜头（可灵默认行为）。
    """
    cfg = get_settings()
    duration_sec = 10 if duration_sec > 7 else 5
    model = cfg.kling_video_model
    mode = MODE_MAP.get(quality, "std")
    if camera_control and model in MODELS_WITHOUT_CAMERA_CONTROL:
        log.info(
            "[Kling] model=%s 在 MODELS_WITHOUT_CAMERA_CONTROL 黑名单，跳过 camera_control（节省 1201 重试）",
            model,
        )
        camera_control = None

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    log.info("[Kling] 提交 model=%s mode=%s duration=%ds camera=%s prompt=%s... ref=%s",
             model, mode, duration_sec,
             camera_control.get("type") if camera_control else "default",
             prompt[:50], bool(character_ref_path))

    payload = {
        "model_name": model,
        "mode": mode,
        "image": img_b64,
        "prompt": prompt,
        "duration": str(duration_sec),
        "aspect_ratio": aspect_ratio,
    }

    # 部署日真修：可灵 v2+ 已弃用 push_in/pull_out/orbit 等旧 type
    # 映射到 simple+config 六轴；不能映射的（含 static）去掉 camera_control 字段
    normalized_camera = normalize_camera_control(camera_control)
    if normalized_camera:
        payload["camera_control"] = normalized_camera
        log.info(
            "[Kling] camera_control 旧→新映射：%s → %s",
            camera_control.get("type") if camera_control else None,
            normalized_camera,
        )

    if character_ref_path and os.path.isfile(character_ref_path):
        with open(character_ref_path, "rb") as f:
            ref_b64 = base64.b64encode(f.read()).decode()
        payload["character_ref"] = ref_b64
        log.info("[Kling] 角色参考图已注入视频生成")

    async with httpx.AsyncClient(timeout=300) as c:
        resp = await c.post(
            f"{cfg.kling_base_url}/v1/videos/image2video",
            headers=kling_headers(),
            json=payload,
        )
        resp_data = resp.json()
        # 兜底：camera_control 仍报错（1201）→ 剥离重试一次
        if resp_data.get("code") == 1201 and "camera_control" in payload:
            log.warning(
                "[Kling] 1201 camera_control invalid (%s)，剥离 camera_control 后重试",
                resp_data.get("message"),
            )
            payload_retry = {k: v for k, v in payload.items() if k != "camera_control"}
            resp = await c.post(
                f"{cfg.kling_base_url}/v1/videos/image2video",
                headers=kling_headers(),
                json=payload_retry,
            )
            resp_data = resp.json()
        if resp_data.get("code") != 0:
            raise RuntimeError(f"可灵提交失败: {resp_data.get('message')} | {resp_data}")

        task_id = resp_data["data"]["task_id"]
        log.info("[Kling] task_id=%s, 开始轮询", task_id)

        delay = 5
        elapsed = 0
        max_wait = 600  # 最多等 10 分钟（更长视频需要更多生成时间）

        while elapsed < max_wait:
            await asyncio.sleep(delay)
            elapsed += delay

            st = await c.get(
                f"{cfg.kling_base_url}/v1/videos/image2video/{task_id}",
                headers=kling_headers(),
            )
            data = st.json().get("data", {})
            status = data.get("task_status")

            if status == "succeed":
                video_url = data["task_result"]["videos"][0]["url"]
                log.info("[Kling] 成功，下载视频")

                raw = await c.get(video_url)
                os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(raw.content)

                return VideoResult(
                    url=video_url,
                    local_path=output_path,
                    duration_sec=duration_sec,
                    task_id=task_id,
                    model=f"{model}/{mode}",
                )

            if status == "failed":
                raise RuntimeError(f"可灵生成失败: {data.get('task_status_msg')}")

            log.debug("[Kling] 状态=%s, 已等待%ds", status, elapsed)
            # 指数退避，上限 20s
            delay = min(delay * 1.3, 20)

    raise RuntimeError(f"可灵生成超时（{max_wait}秒），task_id={task_id}")
