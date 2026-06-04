"""音效生成模块

根据脚本场景描述，通过 LLM 智能匹配音效，支持本地素材库 + 在线生成。
"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from config.settings import get_settings
from integrations.llm_client import get_deepseek

logger = logging.getLogger(__name__)

# ── 内置音效分类库 ──
# key: 音效类别标签, value: 描述（用于 LLM 匹配）
SFX_CATEGORIES: dict[str, dict] = {
    # 环境
    "city_traffic": {"name": "城市交通", "tags": ["城市", "马路", "汽车", "喇叭", "都市"]},
    "office": {"name": "办公室", "tags": ["办公", "键盘", "打字", "上班", "工位"]},
    "nature_birds": {"name": "鸟叫自然", "tags": ["鸟", "森林", "树林", "自然", "户外"]},
    "rain": {"name": "下雨", "tags": ["雨", "雨声", "暴雨", "细雨", "雨天"]},
    "wind": {"name": "风声", "tags": ["风", "大风", "微风", "呼啸"]},
    "ocean": {"name": "海浪", "tags": ["海", "海浪", "海边", "沙滩", "大海"]},
    "thunder": {"name": "雷声", "tags": ["雷", "打雷", "闪电", "暴风雨"]},
    "fire": {"name": "火焰", "tags": ["火", "燃烧", "篝火", "火焰"]},
    "crowd": {"name": "人群嘈杂", "tags": ["人群", "嘈杂", "热闹", "广场", "市集"]},
    # 动作
    "explosion": {"name": "爆炸", "tags": ["爆炸", "炸", "轰", "军事", "战斗"]},
    "footsteps": {"name": "脚步声", "tags": ["走路", "脚步", "跑步", "奔跑"]},
    "door": {"name": "开关门", "tags": ["门", "开门", "关门", "敲门"]},
    "punch": {"name": "打击", "tags": ["打", "拳", "格斗", "碰撞", "撞击"]},
    "whoosh": {"name": "嗖的一声", "tags": ["嗖", "飞过", "快速", "冲刺", "划过"]},
    "splash": {"name": "水花", "tags": ["水", "溅", "跳水", "水花", "泼水"]},
    # 情绪/转场
    "suspense": {"name": "悬疑紧张", "tags": ["悬疑", "紧张", "恐怖", "惊悚", "阴森"]},
    "comedy": {"name": "搞笑音效", "tags": ["搞笑", "滑稽", "喜剧", "笑", "幽默"]},
    "success": {"name": "成功/胜利", "tags": ["成功", "胜利", "达成", "完成", "赢"]},
    "fail": {"name": "失败", "tags": ["失败", "摔倒", "掉落", "出错", "翻车"]},
    "heartbeat": {"name": "心跳", "tags": ["心跳", "紧张", "激动", "心脏"]},
    "notification": {"name": "提示音", "tags": ["提示", "通知", "消息", "叮", "铃"]},
    # 动物
    "cat_meow": {"name": "猫叫", "tags": ["猫", "喵", "猫咪", "猫叫"]},
    "dog_bark": {"name": "狗叫", "tags": ["狗", "汪", "狗叫", "犬"]},
}

SFX_LIBRARY_DIR = Path("assets/sfx")


@dataclass
class SFXItem:
    category: str
    name: str
    timestamp_sec: float
    duration_sec: float
    file_path: Path | None = None


@dataclass
class SFXPlan:
    scene_desc: str
    items: list[SFXItem] = field(default_factory=list)


_SFX_MATCH_PROMPT = """\
你是一个短视频音效设计师。根据场景描述，从可用音效库中选择合适的环境音效和动作音效。

可用音效类别：
{categories}

规则：
1. 每个场景选 1-3 个音效，不要过多
2. 为每个音效指定出现的时间点（秒）和持续时长（秒）
3. 环境音可以贯穿整个场景，动作音效在关键时刻出现
4. 输出纯 JSON 数组

输出格式（严格 JSON，无其他文字）：
[
  {{"category": "音效类别key", "timestamp_sec": 0.0, "duration_sec": 5.0, "reason": "简述原因"}}
]
"""


async def analyze_scene_sfx(
    scene_desc: str,
    video_duration_sec: float = 10.0,
) -> SFXPlan:
    """用 LLM 分析场景，返回音效方案"""
    categories_text = "\n".join(
        f"- {key}: {info['name']}（关键词：{', '.join(info['tags'][:3])}）"
        for key, info in SFX_CATEGORIES.items()
    )

    system_prompt = _SFX_MATCH_PROMPT.format(categories=categories_text)
    user_prompt = f"场景描述：{scene_desc}\n视频时长：{video_duration_sec}秒"

    resp = await get_deepseek().chat.completions.create(
        model=get_settings().deepseek_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=500,
        temperature=0.3,
    )

    raw = resp.choices[0].message.content.strip()
    raw = raw.removeprefix("```json").removesuffix("```").strip()

    try:
        items_data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("SFX LLM output parse failed: %s", raw[:200])
        return SFXPlan(scene_desc=scene_desc, items=[])

    items: list[SFXItem] = []
    for item in items_data:
        cat = item.get("category", "")
        if cat not in SFX_CATEGORIES:
            logger.warning("Unknown SFX category from LLM: %s", cat)
            continue
        items.append(SFXItem(
            category=cat,
            name=SFX_CATEGORIES[cat]["name"],
            timestamp_sec=float(item.get("timestamp_sec", 0)),
            duration_sec=float(item.get("duration_sec", 3)),
            file_path=_resolve_sfx_file(cat),
        ))

    logger.info("SFX plan for '%s': %d effects", scene_desc[:30], len(items))
    return SFXPlan(scene_desc=scene_desc, items=items)


def _resolve_sfx_file(category: str) -> Path | None:
    """从本地素材库查找对应音效文件"""
    sfx_dir = SFX_LIBRARY_DIR / category
    if not sfx_dir.exists():
        return None
    candidates = list(sfx_dir.glob("*.mp3")) + list(sfx_dir.glob("*.wav"))
    if not candidates:
        return None
    return candidates[0]


async def batch_analyze(
    scenes: list[dict],
    video_duration_sec: float = 10.0,
) -> list[SFXPlan]:
    """批量分析多个场景的音效需求

    Args:
        scenes: [{"scene_desc": "...", "duration_sec": 5.0}, ...]
    """
    plans = []
    for scene in scenes:
        plan = await analyze_scene_sfx(
            scene_desc=scene.get("scene_desc", ""),
            video_duration_sec=scene.get("duration_sec", video_duration_sec),
        )
        plans.append(plan)
    return plans


def import_sfx_file(src: Path | str, category: str, name: str = "") -> Path:
    """导入自定义音效文件到素材库"""
    src = Path(src)
    if not src.exists():
        raise FileNotFoundError(f"SFX source not found: {src}")

    target_dir = SFX_LIBRARY_DIR / category
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = name or src.name
    target = target_dir / filename
    shutil.copy2(src, target)
    logger.info("Imported SFX: %s -> %s", src, target)
    return target


def list_categories() -> list[dict]:
    """返回所有可用音效类别"""
    result = []
    for key, info in SFX_CATEGORIES.items():
        sfx_dir = SFX_LIBRARY_DIR / key
        file_count = len(list(sfx_dir.glob("*"))) if sfx_dir.exists() else 0
        result.append({
            "key": key,
            "name": info["name"],
            "tags": info["tags"],
            "file_count": file_count,
        })
    return result
