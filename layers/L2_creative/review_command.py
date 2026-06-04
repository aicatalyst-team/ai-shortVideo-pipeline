"""Phase P Sprint P4：用户审核命令的结构化 parse。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Action = Literal["continue", "regenerate", "cancel", "unknown"]

_HINT_KEYWORDS: dict[str, list[str]] = {
    "closer_shot": ["人物近", "镜头近", "再近一点", "拉近", "近一些", "近点"],
    "wider_shot": ["远一点", "远一些", "拉远", "镜头远", "宽一点"],
    "more_realistic": ["更真实", "真实一点", "纪实感", "不要油腻", "去油腻", "纪录片"],
    "more_dramatic": ["更戏剧", "更夸张", "更震撼", "广告片感", "电影感强"],
    "no_text": ["不要文字", "不要字", "去掉文字", "无文字", "去掉乱码", "无字幕"],
    "brighter": ["亮一点", "亮一些", "更亮", "提亮"],
    "darker": ["暗一点", "暗一些", "更暗", "压暗"],
    "warmer_tone": ["暖色", "暖一点", "暖色调"],
    "cooler_tone": ["冷色", "冷一点", "冷色调"],
    "more_motion": ["动一点", "更动态", "动作大一点"],
    "static_shot": ["静一点", "别动", "静态", "固定镜头"],
    "different_character": ["换人", "换角色", "换主角", "另一个人"],
    "different_scene": ["换场景", "换地方", "换背景"],
}


class ReviewCommand(BaseModel):
    """结构化审核命令。"""

    action: Action = Field(...)
    raw_note: str = Field(default="")
    hints: list[str] = Field(default_factory=list)
    structured_notes: list[str] = Field(default_factory=list)

    @property
    def is_actionable(self) -> bool:
        return self.action in ("continue", "regenerate", "cancel")


def parse_review_command(text: str) -> ReviewCommand:
    """解析用户审核回复 → ReviewCommand。"""
    raw = (text or "").strip()
    if not raw:
        return ReviewCommand(action="unknown")

    if raw in {"1", "1.", "1.继续", "继续", "确认", "确认片段"}:
        return ReviewCommand(action="continue", raw_note="")

    note = ""
    action: Action = "unknown"
    if raw.startswith("2") or raw.startswith("重新生成"):
        action = "regenerate"
        for sep in (":", "："):
            if sep in raw:
                note = raw.split(sep, 1)[1].strip()
                break
    elif raw.startswith("3") or raw.startswith("取消"):
        action = "cancel"
        for sep in (":", "："):
            if sep in raw:
                note = raw.split(sep, 1)[1].strip()
                break
    else:
        return ReviewCommand(action="unknown", raw_note=raw)

    hints, leftovers = _extract_hints(note)
    return ReviewCommand(
        action=action,
        raw_note=note,
        hints=hints,
        structured_notes=leftovers,
    )


def _extract_hints(note: str) -> tuple[list[str], list[str]]:
    """从 note 找命中的 hint 关键字；剩余短语切分到 structured_notes。"""
    if not note:
        return [], []

    import re

    parts = [p.strip() for p in re.split(r"[+,，、；\s]+", note) if p.strip()]
    hits: list[str] = []
    leftovers: list[str] = []
    for part in parts:
        matched = False
        for hint_key, keywords in _HINT_KEYWORDS.items():
            if any(kw in part for kw in keywords):
                if hint_key not in hits:
                    hits.append(hint_key)
                matched = True
                break
        if not matched:
            leftovers.append(part)
    return hits, leftovers
