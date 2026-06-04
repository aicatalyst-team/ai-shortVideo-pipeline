"""视频质量关卡

发布前对生成的视频进行多维度打分，低分自动拦截并反馈重生原因。

评分维度：
- 首帧吸引力（通过 LLM 分析 image_prompt 质量）
- 解说稿质量（可读性 / 信息密度 / 爆款结构）
- 节奏密度（attention_points 密度）
- 技术指标（文件大小 / 时长合规）
- 配音匹配（音色 / 语速是否适合垂类）

总分 0-100，低于阈值（默认 70）拦截并输出重生建议。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from config.settings import get_settings
from core.parsers import parse_json_object
from integrations.llm_client import get_deepseek

log = logging.getLogger(__name__)

PASS_THRESHOLD = 70  # 低于此分数拦截重生


@dataclass
class QualityScore:
    total: float
    passed: bool
    dimensions: dict[str, float] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


async def score_content(
    narration: str,
    image_prompt: str,
    style_name: str,
    rhythm_density: float = 0.0,
    voice_key: str = "",
) -> QualityScore:
    """对解说稿 + 配图描述进行内容质量打分（不需要视频文件）。"""
    log.info("[质量关卡] 内容打分 style=%s", style_name)

    system_prompt = (
        "你是短视频内容质量评审专家。\n\n"
        "评分任务：对给定的解说稿和配图描述进行综合质量评估。\n\n"
        "评分维度（各维度满分 100）：\n"
        "1. hook_score（开场钩子）：前3秒是否足够抓人，有无认知冲突或情感冲击\n"
        "2. content_score（内容质量）：信息密度、口语化程度、有无AI味、是否像真人写的\n"
        "3. structure_score（叙事结构）：Hook→核心信息→情感落点→CTA 是否完整\n"
        "4. visual_score（配图匹配度）：image_prompt 描述的画面是否与解说内容强相关\n"
        "5. viral_score（爆款潜力）：是否有讨论点、转发点、评论欲\n\n"
        "输出严格的 JSON：\n"
        "{\n"
        '  "hook_score": 75,\n'
        '  "content_score": 80,\n'
        '  "structure_score": 70,\n'
        '  "visual_score": 85,\n'
        '  "viral_score": 65,\n'
        '  "issues": ["问题1", "问题2"],\n'
        '  "suggestions": ["改进建议1", "改进建议2"]\n'
        "}\n"
        "只输出 JSON，不要其他文字。"
    )

    user_msg = (
        f"风格垂类：{style_name}\n\n"
        f"解说稿：\n{narration[:800]}\n\n"
        f"配图描述：\n{image_prompt[:200]}"
    )

    resp = await get_deepseek().chat.completions.create(
        model=get_settings().deepseek_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=600,
    )

    raw = resp.choices[0].message.content.strip()
    data = parse_json_object(raw)

    dim_keys = ["hook_score", "content_score", "structure_score", "visual_score", "viral_score"]
    weights = {"hook_score": 0.30, "content_score": 0.25, "structure_score": 0.20,
               "visual_score": 0.15, "viral_score": 0.10}

    dimensions = {k: float(data.get(k, 60)) for k in dim_keys}

    # 节奏密度加分（2-4/10s 为理想区间）
    rhythm_bonus = 0.0
    if 2 <= rhythm_density <= 4:
        rhythm_bonus = 5.0
    elif rhythm_density < 1:
        rhythm_bonus = -5.0
    dimensions["rhythm_density"] = rhythm_density * 10  # 转换为百分制参考值

    total = sum(dimensions[k] * weights[k] for k in dim_keys) + rhythm_bonus
    total = max(0, min(100, total))

    issues = data.get("issues", [])
    suggestions = data.get("suggestions", [])

    # 技术规则检查（不依赖 LLM）
    if len(narration) < 100:
        issues.append("解说稿过短（<100字），信息量不足")
        suggestions.append("扩充解说稿到 200 字以上")
        total -= 10
    if not image_prompt:
        issues.append("缺少配图描述，无法生成配图")
        total -= 15

    passed = total >= PASS_THRESHOLD
    log.info("[质量关卡] 总分=%.1f %s", total, "✅通过" if passed else "❌拦截")

    return QualityScore(
        total=round(total, 1),
        passed=passed,
        dimensions=dimensions,
        issues=issues,
        suggestions=suggestions,
    )


def score_video_file(video_path: str, style_name: str) -> dict[str, float]:
    """对已生成的视频文件进行技术指标检查（不调用 LLM）。"""
    result: dict[str, float] = {}

    if not os.path.exists(video_path):
        return {"file_exists": 0}

    size_mb = os.path.getsize(video_path) / 1024 / 1024
    result["size_mb"] = size_mb

    # 抖音限制：<500MB，推荐 <50MB
    if size_mb > 500:
        result["size_score"] = 0
    elif size_mb > 50:
        result["size_score"] = 70
    else:
        result["size_score"] = 100

    return result


def format_quality_report(score: QualityScore) -> str:
    status = "✅ 通过质量关卡" if score.passed else f"❌ 质量不足（{score.total:.0f}/100），需要重生"
    lines = [f"质量评分：{score.total:.0f}/100  {status}\n"]

    dim_names = {
        "hook_score": "开场钩子",
        "content_score": "内容质量",
        "structure_score": "叙事结构",
        "visual_score": "配图匹配",
        "viral_score": "爆款潜力",
    }
    for k, name in dim_names.items():
        v = score.dimensions.get(k, 0)
        bar = "█" * int(v // 10) + "░" * (10 - int(v // 10))
        lines.append(f"  {name:6s} {bar} {v:.0f}")

    if score.issues:
        lines.append("\n问题：")
        for issue in score.issues:
            lines.append(f"  ⚠️ {issue}")

    if score.suggestions and not score.passed:
        lines.append("\n改进建议：")
        for s in score.suggestions:
            lines.append(f"  → {s}")

    return "\n".join(lines)
