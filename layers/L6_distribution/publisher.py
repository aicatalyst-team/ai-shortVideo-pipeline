"""
Phase 3 — Video delivery via Feishu notification.

Auto-publishing to Douyin/Bilibili/Xiaohongshu has been deferred:
platform APIs are enterprise-only, and Playwright automation is too
fragile for a solo developer to maintain long-term.

Current approach: push a Feishu card with title, cover, and download
link so the creator can publish manually.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def build_publish_card(
    title: str,
    video_path: str,
    tags: list[str],
    cover_path: Optional[str] = None,
) -> str:
    """Build a Feishu message summarising the video ready for manual publish."""
    tag_str = " ".join(f"#{t}" for t in tags[:8]) if tags else ""
    lines = [
        f"📹 视频已就绪\n",
        f"标题：{title}",
        f"标签：{tag_str}" if tag_str else None,
        f"视频：{video_path}",
        f"封面：{cover_path}" if cover_path else None,
        "",
        "请手动发布到各平台。",
    ]
    return "\n".join(l for l in lines if l is not None)
