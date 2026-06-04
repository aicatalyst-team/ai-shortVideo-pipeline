"""注意力曲线引擎

用 LLM 分析解说稿，标注每个时间节点的"刺激点"——
画面切换、音效触发、字幕放大等操作的触发时机。

输出给 rhythm_editor.py 用于节奏化剪辑。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from config.settings import get_settings
from core.parsers import parse_json_object
from integrations.llm_client import get_deepseek

log = logging.getLogger(__name__)


@dataclass
class AttentionPoint:
    timestamp_sec: float       # 触发时间（秒）
    point_type: str            # cut / sfx / caption_zoom / bgm_swell / pause
    intensity: int             # 1-5，刺激强度
    description: str           # 该刺激点的内容描述
    narration_trigger: str     # 触发该刺激点的旁白文字


@dataclass
class RhythmPlan:
    total_duration_sec: float
    attention_points: list[AttentionPoint] = field(default_factory=list)
    density_score: float = 0.0   # 每10秒刺激点数量，理想值 2-4

    def points_per_interval(self, interval_sec: float = 5.0) -> list[list[AttentionPoint]]:
        """将刺激点按时间区间分组，便于 rhythm_editor 逐段处理。"""
        if not self.attention_points:
            return []
        buckets: dict[int, list[AttentionPoint]] = {}
        for pt in self.attention_points:
            bucket = int(pt.timestamp_sec // interval_sec)
            buckets.setdefault(bucket, []).append(pt)
        max_bucket = int(self.total_duration_sec // interval_sec)
        return [buckets.get(i, []) for i in range(max_bucket + 1)]


# 刺激点类型说明（给 LLM 参考）
POINT_TYPE_DESC = {
    "cut":           "画面切换（切到下一个镜头/配图）",
    "sfx":           "音效触发（加入环境音/强调音效）",
    "caption_zoom":  "字幕放大高亮（关键词放大）",
    "bgm_swell":     "BGM 升调（情绪推进时音乐配合）",
    "pause":         "画面停留（让观众消化信息，0.5-1秒停顿）",
}


async def annotate_rhythm(
    narration: str,
    total_duration_sec: float,
    style_name: str = "hot_news_commentary",
) -> RhythmPlan:
    """分析解说稿，输出注意力曲线标注。"""
    log.info("[节奏引擎] 标注 %.0fs 解说稿，风格=%s", total_duration_sec, style_name)

    point_types_desc = "\n".join(f"  - {k}: {v}" for k, v in POINT_TYPE_DESC.items())

    system_prompt = (
        "你是短视频剪辑节奏专家，擅长分析解说类视频的注意力曲线。\n\n"
        "任务：分析给定的解说稿，标注哪些时间点需要「刺激」观众注意力。\n\n"
        "刺激点类型：\n"
        f"{point_types_desc}\n\n"
        "节奏规则（解说类视频）：\n"
        "1. 前 3 秒必须有高强度刺激（Hook 结束时配合画面切换）\n"
        "2. 每 3-5 秒应有 1 个刺激点，避免超过 5 秒无变化\n"
        "3. 数据/结论出现时用 caption_zoom 强调\n"
        "4. 情绪转折点用 bgm_swell 配合\n"
        "5. 结尾 3 秒用 pause + sfx 强化记忆点\n\n"
        "输出严格的 JSON，格式：\n"
        "{\n"
        '  "total_duration_sec": 30,\n'
        '  "attention_points": [\n'
        '    {\n'
        '      "timestamp_sec": 3.0,\n'
        '      "point_type": "cut",\n'
        '      "intensity": 5,\n'
        '      "description": "Hook结束，切换到数据配图",\n'
        '      "narration_trigger": "对应的旁白文字"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "只输出 JSON，不要其他文字。"
    )

    user_msg = (
        f"解说稿总时长约 {total_duration_sec:.0f} 秒，请标注注意力刺激点：\n\n{narration}"
    )

    resp = await get_deepseek().chat.completions.create(
        model=get_settings().deepseek_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=1500,
    )

    raw = resp.choices[0].message.content.strip()
    log.info("[节奏引擎] 返回 %d 字", len(raw))

    data = parse_json_object(raw)
    duration = float(data.get("total_duration_sec", total_duration_sec))

    points = []
    for item in data.get("attention_points", []):
        points.append(AttentionPoint(
            timestamp_sec=float(item.get("timestamp_sec", 0)),
            point_type=item.get("point_type", "cut"),
            intensity=int(item.get("intensity", 3)),
            description=item.get("description", ""),
            narration_trigger=item.get("narration_trigger", ""),
        ))

    points.sort(key=lambda p: p.timestamp_sec)

    density = len(points) / (duration / 10) if duration > 0 else 0
    log.info("[节奏引擎] 共 %d 个刺激点，密度=%.1f/10s", len(points), density)

    return RhythmPlan(
        total_duration_sec=duration,
        attention_points=points,
        density_score=density,
    )


def format_rhythm_plan(plan: RhythmPlan) -> str:
    lines = [f"节奏标注（总时长 {plan.total_duration_sec:.0f}s，密度 {plan.density_score:.1f}/10s）：\n"]
    for pt in plan.attention_points:
        intensity_bar = "█" * pt.intensity + "░" * (5 - pt.intensity)
        lines.append(
            f"  {pt.timestamp_sec:5.1f}s │{intensity_bar}│ [{pt.point_type}] {pt.description}"
        )
    ideal = "✅ 理想" if 2 <= plan.density_score <= 4 else ("⚠️ 偏稀" if plan.density_score < 2 else "⚠️ 过密")
    lines.append(f"\n节奏密度评价：{ideal}")
    return "\n".join(lines)
