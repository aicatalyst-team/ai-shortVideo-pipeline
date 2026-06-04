""" creative chains backed by strict Pydantic schemas.

Design principles:
1. Keep legacy chains.py untouched so the current Feishu flow remains stable.
2. v2 functions return Pydantic objects instead of JSON strings.
3. Invalid LLM output is retried with the concrete schema error.
4. Exhausted retries raise SchemaValidationError with the last raw output.
"""

from __future__ import annotations

import asyncio
import json
import logging

from pydantic import ValidationError

from config.settings import get_settings
from core.langfuse_client import observe
from core.parsers import parse_json_object
from integrations.llm_client import get_deepseek, get_glm
from layers.L2_creative.character_manager import list_characters
from layers.L2_creative.environment_manager import list_environments
from layers.L2_creative.schemas import SchemaValidationError, ScoreReport, Storyboard
from layers.L2_creative.style_engine import StyleTemplate

log = logging.getLogger(__name__)


def _build_creative_system_prompt(style: StyleTemplate, extra_context: str = "") -> str:
    """Inject Storyboard schema and available world assets into the prompt."""
    schema = Storyboard.model_json_schema()
    char_ids = [c.key for c in list_characters()]
    env_ids = [e.key for e in list_environments()]

    return (
        f"{style.system_prompt(extra_context)}\n\n"
        "你是分镜导演 AI。任务：根据用户主题生成一条短视频分镜板。\n\n"
        "【硬约束】输出必须严格符合以下 JSON Schema，每个字段、枚举值都不能偏差：\n"
        f"```json\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n```\n\n"
        f"【character_id 只能从这些选】：{char_ids}\n"
        f"【environment_id 只能从这些选】：{env_ids}\n\n"
        "【输出要求】\n"
        "1. 纯 JSON 对象，不要 markdown 代码块包裹\n"
        "2. shots 数量建议 5-8（短视频信息密度优于电影感）\n"
        "3. scene_no 必须从 1 连续\n"
        "4. total_duration_sec 必须 = 所有 shots 的 estimated_duration_sec 之和（±2s 容差）\n"
        "5. main_character_id 必须出现在至少一个 shot.character_id 中\n"
        "6. 每个 shot 的 key_props 必须从 narration_segment 中抽取实体（防止画面与旁白脱节）\n"
        "7. 镜头多样性硬约束（Schema 强制，违反会被拒绝重试）：\n"
        "   - 5 shots 及以上时，shots 的 position.camera_distance 至少要有 2 种不同值\n"
        "   - 8 shots 及以上时，至少要有 3 种不同值\n"
        "   - 推荐组合：medium / close_up / wide / medium_close / extreme_close 等轮换\n\n"
        "8. 旁白字数硬约束（Schema 强制按 duration 校验，违反必然被拒绝重试）：\n"
        "   - estimated_duration_sec <= 2.5：narration_segment 最多 20 字\n"
        "   - 2.5 < duration <= 4.5：最多 30 字\n"
        "   - 4.5 < duration <= 7.5：最多 40 字（5 秒片段主档，建议 18-35 字）\n"
        "   - 7.5 < duration <= 9.5：最多 60 字\n"
        "   - duration > 9.5：最多 82 字（10 秒片段主档，建议 36-75 字）\n"
        "   - 中文朗读约 7-8 字/秒；超字数 TTS 朗读会比视频长，导致音画漂移被拒绝发布\n"
        "   - 字数 = len(narration_segment)（含中英文/标点/数字，不算前后空格）\n\n"
        "【失败处罚】如果输出违反 schema，会被重试，重试时附带具体错误。"
    )


@observe(name="lobster_creative_v2", as_type="generation")
async def lobster_creative_v2(
    theme: str,
    style: StyleTemplate,
    *,
    main_character_id: str = "su_wan",
    extra_context: str = "",
    max_retries: int = 2,
) -> Storyboard:
    """Generate one structured Storyboard, retrying invalid LLM output."""
    log.info("[creative_v2] theme=%s style=%s main_char=%s", theme, style.name, main_character_id)

    cfg = get_settings()
    system_prompt = _build_creative_system_prompt(style, extra_context)
    user_prompt = (
        f"主题：{theme}\n"
        f"主角：{main_character_id}\n"
        f"风格：{style.name}\n\n"
        "请直接输出符合 schema 的 Storyboard JSON 对象。"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    last_raw = ""
    last_error = ""

    for attempt in range(max_retries + 1):
        log.info("[creative_v2] attempt %d/%d", attempt + 1, max_retries + 1)

        try:
            resp = await get_deepseek().chat.completions.create(
                model=cfg.deepseek_model,
                messages=messages,
                max_tokens=4000,
                temperature=0.7,
            )
            raw = resp.choices[0].message.content or ""
            last_raw = raw
        except Exception as e:
            log.error("[creative_v2] DeepSeek call failed attempt=%d: %s", attempt + 1, e)
            last_error = f"DeepSeek call failed: {e}"
            if attempt < max_retries:
                continue
            raise SchemaValidationError(max_retries + 1, last_error, last_raw)

        try:
            obj = parse_json_object(raw)
            obj["main_character_id"] = main_character_id
            storyboard = Storyboard(**obj)
            log.info("[creative_v2] success attempt=%d shots=%d", attempt + 1, len(storyboard.shots))
            return storyboard
        except (ValidationError, ValueError, json.JSONDecodeError) as e:
            last_error = str(e)
            log.warning("[creative_v2] schema validation failed attempt=%d: %s", attempt + 1, e)
            if attempt < max_retries:
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"你上次的输出违反了 schema：\n{e}\n\n"
                            "请严格按照 schema 重新输出。注意：必须是纯 JSON 对象，不要 markdown 包裹。"
                        ),
                    }
                )
                continue
            raise SchemaValidationError(max_retries + 1, last_error, last_raw)

    raise SchemaValidationError(max_retries + 1, last_error, last_raw)


def _build_evaluate_system_prompt() -> str:
    schema = ScoreReport.model_json_schema()
    return (
        "你是短视频内容评审专家。任务：给一条分镜板（Storyboard）五维打分。\n\n"
        "【五个评估维度】\n"
        "1. hook（开场吸引力）：前 3 秒能否留住观众\n"
        "2. narrative（叙事完整度）：信息密度 / 逻辑连贯 / 价值感\n"
        "3. visual（视觉协调）：画面与旁白匹配 / 角色一致 / 镜头多样\n"
        "4. rhythm（节奏感）：shots 数 / 时长分配 / 转场密度\n"
        "5. potential（爆款潜力）：争议性 / 共鸣点 / 评论引导\n\n"
        "【硬约束】输出必须严格符合以下 JSON Schema：\n"
        f"```json\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n```\n\n"
        "【verdict 判定标准】\n"
        "- pass: overall_score >= 75\n"
        "- needs_revision: 60 <= overall_score < 75\n"
        "- fail: overall_score < 60\n\n"
        "【输出要求】纯 JSON 对象，不要 markdown 包裹。"
    )


@observe(name="lobster_evaluate_v2", as_type="generation")
async def lobster_evaluate_v2(
    storyboard: Storyboard,
    *,
    max_retries: int = 2,
) -> ScoreReport:
    """Evaluate one Storyboard with five score dimensions."""
    log.info("[evaluate_v2] plan_id=%s shots=%d", storyboard.plan_id, len(storyboard.shots))

    cfg = get_settings()
    system_prompt = _build_evaluate_system_prompt()
    storyboard_json = storyboard.model_dump_json(indent=2)
    user_prompt = (
        f"请评审以下 Storyboard（plan_id={storyboard.plan_id}）：\n\n"
        f"```json\n{storyboard_json}\n```\n\n"
        "请直接输出符合 ScoreReport schema 的 JSON 对象。"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    last_error = ""
    last_raw = ""

    for attempt in range(max_retries + 1):
        log.info("[evaluate_v2] attempt %d/%d", attempt + 1, max_retries + 1)

        try:
            def _glm_call():
                return get_glm().chat.completions.create(
                    model=cfg.glm_model_id,
                    messages=messages,
                )

            resp = await asyncio.to_thread(_glm_call)
            raw = resp.choices[0].message.content or ""
            last_raw = raw
        except Exception as e:
            log.error("[evaluate_v2] GLM call failed attempt=%d: %s", attempt + 1, e)
            last_error = f"GLM call failed: {e}"
            if attempt < max_retries:
                continue
            raise SchemaValidationError(max_retries + 1, last_error, last_raw)

        try:
            obj = parse_json_object(raw)
            obj["storyboard_plan_id"] = storyboard.plan_id
            report = ScoreReport(**obj)
            log.info("[evaluate_v2] success score=%.1f verdict=%s", report.overall_score, report.verdict)
            return report
        except (ValidationError, ValueError, json.JSONDecodeError) as e:
            last_error = str(e)
            log.warning("[evaluate_v2] schema validation failed attempt=%d: %s", attempt + 1, e)
            if attempt < max_retries:
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": f"输出违反 schema：\n{e}\n\n请重新输出。",
                    }
                )
                continue
            raise SchemaValidationError(max_retries + 1, last_error, last_raw)

    raise SchemaValidationError(max_retries + 1, last_error, last_raw)
