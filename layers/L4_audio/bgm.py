"""BGM 选择/匹配模块

根据脚本情绪和风格，从本地 BGM 素材库智能匹配背景音乐。
支持 LLM 情绪分析 + 标签匹配双模式。
"""
from __future__ import annotations

import json
import logging
import random
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from config.settings import get_settings
from integrations.llm_client import get_deepseek

logger = logging.getLogger(__name__)

BGM_LIBRARY_DIR = Path("assets/bgm")

# ── 情绪标签体系 ──
Mood = Literal[
    "epic",        # 燃/热血/史诗
    "funny",       # 搞笑/滑稽/欢乐
    "healing",     # 治愈/温暖/舒缓
    "suspense",    # 悬疑/紧张/惊悚
    "sad",         # 伤感/忧郁/抒情
    "romantic",    # 浪漫/甜蜜/爱情
    "chill",       # 轻松/日常/休闲
    "cyberpunk",   # 赛博朋克/科技/电子
    "chinese",     # 国风/古风/中国风
    "military",    # 军事/战斗/硬核
]

MOOD_INFO: dict[str, dict] = {
    "epic":      {"name": "燃/热血", "keywords": ["燃", "热血", "史诗", "激燃", "震撼", "壮观", "战斗", "英雄"]},
    "funny":     {"name": "搞笑/欢乐", "keywords": ["搞笑", "滑稽", "欢乐", "喜剧", "沙雕", "无厘头", "幽默", "可爱"]},
    "healing":   {"name": "治愈/温暖", "keywords": ["治愈", "温暖", "舒缓", "温馨", "感动", "暖心", "阳光"]},
    "suspense":  {"name": "悬疑/紧张", "keywords": ["悬疑", "紧张", "恐怖", "惊悚", "阴森", "诡异", "神秘"]},
    "sad":       {"name": "伤感/忧郁", "keywords": ["伤感", "忧郁", "难过", "悲伤", "离别", "怀念", "孤独"]},
    "romantic":  {"name": "浪漫/甜蜜", "keywords": ["浪漫", "甜蜜", "爱情", "心动", "告白", "恋爱"]},
    "chill":     {"name": "轻松/日常", "keywords": ["轻松", "日常", "休闲", "散步", "午后", "生活", "平静"]},
    "cyberpunk": {"name": "赛博/科技", "keywords": ["赛博", "科技", "未来", "电子", "机械", "AI", "太空"]},
    "chinese":   {"name": "国风/古风", "keywords": ["国风", "古风", "古典", "仙侠", "武侠", "琵琶", "古筝"]},
    "military":  {"name": "军事/硬核", "keywords": ["军事", "战争", "硬核", "枪战", "特种兵", "行军"]},
}


@dataclass
class BGMMatch:
    mood: str
    mood_name: str
    file_path: Path | None
    confidence: float
    reason: str
    volume_ratio: float = 0.3


_MOOD_ANALYZE_PROMPT = """\
你是一个短视频配乐师。根据视频脚本内容，判断最适合的背景音乐情绪。

可选情绪标签：
{moods}

规则：
1. 只选 1 个最匹配的情绪标签
2. 给出匹配置信度 (0.0-1.0)
3. 建议 BGM 音量比例 (0.0-1.0)，人声为主时建议 0.2-0.3，纯画面时可提高到 0.4-0.6
4. 输出纯 JSON，无其他文字

输出格式：
{{"mood": "标签key", "confidence": 0.85, "volume_ratio": 0.3, "reason": "简述理由"}}
"""


async def analyze_mood(script_text: str) -> BGMMatch:
    """用 LLM 分析脚本情绪，返回 BGM 匹配结果"""
    moods_text = "\n".join(
        f"- {key}: {info['name']}"
        for key, info in MOOD_INFO.items()
    )

    resp = await get_deepseek().chat.completions.create(
        model=get_settings().deepseek_model,
        messages=[
            {"role": "system", "content": _MOOD_ANALYZE_PROMPT.format(moods=moods_text)},
            {"role": "user", "content": f"脚本内容：\n{script_text}"},
        ],
        max_tokens=200,
        temperature=0.2,
    )

    raw = resp.choices[0].message.content.strip()
    raw = raw.removeprefix("```json").removesuffix("```").strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("BGM mood parse failed: %s", raw[:200])
        return BGMMatch(
            mood="chill", mood_name="轻松/日常",
            file_path=_pick_bgm_file("chill"),
            confidence=0.5, reason="LLM 解析失败，使用默认",
        )

    mood = data.get("mood", "chill")
    if mood not in MOOD_INFO:
        mood = "chill"

    return BGMMatch(
        mood=mood,
        mood_name=MOOD_INFO[mood]["name"],
        file_path=_pick_bgm_file(mood),
        confidence=float(data.get("confidence", 0.5)),
        reason=data.get("reason", ""),
        volume_ratio=float(data.get("volume_ratio", 0.3)),
    )


def match_by_keywords(text: str) -> BGMMatch:
    """基于关键词快速匹配情绪（不调用 LLM，适合批量/降本场景）"""
    scores: dict[str, int] = {}
    for mood, info in MOOD_INFO.items():
        score = sum(1 for kw in info["keywords"] if kw in text)
        if score > 0:
            scores[mood] = score

    if not scores:
        mood = "chill"
        confidence = 0.3
    else:
        mood = max(scores, key=scores.get)
        confidence = min(scores[mood] / 3.0, 1.0)

    return BGMMatch(
        mood=mood,
        mood_name=MOOD_INFO[mood]["name"],
        file_path=_pick_bgm_file(mood),
        confidence=confidence,
        reason=f"关键词匹配，命中{scores.get(mood, 0)}个词",
    )


def _pick_bgm_file(mood: str) -> Path | None:
    """从本地素材库随机选一首对应情绪的 BGM"""
    bgm_dir = BGM_LIBRARY_DIR / mood
    if not bgm_dir.exists():
        return None
    candidates = list(bgm_dir.glob("*.mp3")) + list(bgm_dir.glob("*.wav")) + list(bgm_dir.glob("*.m4a"))
    if not candidates:
        return None
    return random.choice(candidates)


def import_bgm(src: Path | str, mood: str, name: str = "") -> Path:
    """导入 BGM 文件到素材库"""
    src = Path(src)
    if not src.exists():
        raise FileNotFoundError(f"BGM source not found: {src}")
    if mood not in MOOD_INFO:
        raise ValueError(f"Unknown mood: {mood}, available: {list(MOOD_INFO)}")

    target_dir = BGM_LIBRARY_DIR / mood
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = name or src.name
    target = target_dir / filename
    shutil.copy2(src, target)
    logger.info("Imported BGM: %s -> %s [%s]", src, target, mood)
    return target


def list_library() -> list[dict]:
    """查看 BGM 素材库概况"""
    result = []
    for mood, info in MOOD_INFO.items():
        bgm_dir = BGM_LIBRARY_DIR / mood
        files = list(bgm_dir.glob("*")) if bgm_dir.exists() else []
        result.append({
            "mood": mood,
            "name": info["name"],
            "file_count": len(files),
            "files": [f.name for f in files[:5]],
        })
    return result
