from __future__ import annotations

import json
import logging

import httpx

from config.settings import get_settings

log = logging.getLogger(__name__)

FEISHU_BASE = "https://open.feishu.cn/open-apis"


async def get_token() -> str | None:
    cfg = get_settings()
    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": cfg.feishu_app_id, "app_secret": cfg.feishu_app_secret},
        )
        data = r.json()
        token = data.get("tenant_access_token")
        if not token:
            log.error("[飞书] token 为空: %s", data)
        return token


async def _auth_headers() -> dict[str, str]:
    token = await get_token()
    if not token:
        raise RuntimeError("飞书 token 获取失败")
    return {"Authorization": f"Bearer {token}"}


async def send_text(chat_id: str, text: str) -> None:
    log.info("[飞书] 发送 %s...", text[:40])
    headers = await _auth_headers()
    async with httpx.AsyncClient() as c:
        resp = await c.post(
            f"{FEISHU_BASE}/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            headers=headers,
            json={
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}),
            },
        )
        result = resp.json()
        if result.get("code") != 0:
            log.error("[飞书] 发送失败: %s", result)


async def send_long(chat_id: str, text: str, chunk: int = 3000) -> None:
    for i in range(0, len(text), chunk):
        await send_text(chat_id, text[i : i + chunk])


async def send_file(
    chat_id: str,
    file_path: str,
    title: str = "video.mp4",
    caption: str = "",
) -> None:
    log.info("[飞书视频] 上传 %s", file_path)
    headers = await _auth_headers()
    async with httpx.AsyncClient(timeout=300) as c:
        with open(file_path, "rb") as f:
            upload_resp = await c.post(
                f"{FEISHU_BASE}/im/v1/files",
                headers=headers,
                data={"file_type": "stream", "file_name": title},
                files={"file": f},
            )
        upload_data = upload_resp.json()
        if upload_data.get("code") != 0:
            log.error("[飞书视频] 上传失败: %s", upload_data)
            await send_text(chat_id, f"视频上传飞书失败：{upload_data.get('msg')}")
            return
        file_key = upload_data["data"]["file_key"]

        send_resp = await c.post(
            f"{FEISHU_BASE}/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            headers={**headers, "Content-Type": "application/json"},
            json={
                "receive_id": chat_id,
                "msg_type": "file",
                "content": json.dumps({"file_key": file_key}),
            },
        )
        result = send_resp.json()
        if result.get("code") != 0:
            log.error("[飞书视频] 发送失败: %s", result)
            return
        log.info("[飞书视频] 发送成功")

    if caption:
        await send_text(chat_id, caption)


async def download_file(
    message_id: str,
    file_key: str,
    save_path: str,
    resource_type: str = "file",
) -> str:
    headers = await _auth_headers()
    url = f"{FEISHU_BASE}/im/v1/messages/{message_id}/resources/{file_key}"
    async with httpx.AsyncClient(timeout=180) as c:
        resp = await c.get(url, headers=headers, params={"type": resource_type})
        if resp.status_code != 200:
            body_text = resp.text[:300] if resp.content else "(empty)"
            raise RuntimeError(f"飞书文件下载失败: HTTP {resp.status_code} | {body_text}")
        ctype = resp.headers.get("Content-Type", "")
        if "application/json" in ctype:
            try:
                data = resp.json()
            except Exception:
                data = {}
            raise RuntimeError(f"飞书文件下载失败: {data.get('msg') or data}")
        if not resp.content:
            raise RuntimeError("飞书文件下载失败: 内容为空")

    with open(save_path, "wb") as f:
        f.write(resp.content)
    return save_path
