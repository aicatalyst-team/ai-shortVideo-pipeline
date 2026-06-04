from __future__ import annotations

from config.settings import get_settings


def content_guard(text: str) -> tuple[bool, str]:
    for kw in get_settings().blocked_keywords:
        if kw in text:
            return False, f"含敏感词[{kw}]"
    return True, "通过"
