from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
import time
import uuid

from fastapi import APIRouter, Request, BackgroundTasks

from config.settings import get_settings
from core.guard import content_guard
from core.parsers import parse_json_array, parse_json_object
from integrations.feishu import send_text, send_long, send_file, download_file
from layers.L2_creative.style_engine import get_template, list_template_names, StyleTemplate
from layers.L2_creative import chains
from layers.L2_creative.creative_skills import (
    format_creative_skills_for_feishu,
    get_creative_skill,
)
from layers.L2_creative.generation_session import (
    create_session as _gs_create,
    emit_event as _gs_emit,
    lock_character as _gs_lock_character,
    lock_storyboard as _gs_lock_storyboard,
    update_session as _gs_update,
)
from layers.L2_creative.rating_service import (
    ScoreOutcome,
    parse_score_reply,
    record_fail,
    record_final_score,
)
from layers.L2_creative.review_command import ReviewCommand, parse_review_command
from layers.L2_creative.prompt_director.anchors import (
    StoryAnchors,
    extract_anchors_from_first_clip,
    inject_anchors_into_prompt,
)
from layers.L2_creative.character_manager import (
    resolve_operator_to_character, list_characters, get_character, get_default_character,
)
from layers.L3_visual.image_to_video import generate_clip_sequence, concat_clips
from layers.L3_visual.prompt_safety import sanitize_visual_prompt
from layers.L4_audio.voiceover import synthesize_with_fallback as tts_synthesize
from layers.L4_audio.sfx import analyze_scene_sfx
from layers.L4_audio.bgm import analyze_mood
from layers.L4_audio.cost_estimator import estimate_clip_cost, estimate_clips_total_cost
from layers.L4_audio.mixer import mix_simple
from layers.L4_audio.audio_analyzer import analyze_audio
from layers.L4_audio.visual_planner import (
    ClipPlan,
    estimate_narration_audio_sec,
    format_plan_for_feishu,
    plan_clip_durations,
)
from layers.L5_postprod.captions import burn_captions, burn_captions_from_word_timestamps, CaptionItem
from layers.L5_postprod.text_normalizer import to_simplified_zh
from layers.L5_postprod.cover import generate_cover
from layers.L5_postprod.multi_ratio import generate_all_ratios
from layers.L5_postprod.editor import compress
from layers.L5_postprod.av_sync import (
    AVDriftTooLargeError,
    AvSyncReport,
    check_and_correct_av_sync,
)
from layers.L5_postprod.av_sync_rescue import attempt_rescue

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])
_sem = asyncio.Semaphore(1)

# 会话级中间状态存储（per chat_id）
# 保存创意链产出的脚本和评估结果，供「确认」时取用
_session_store: dict[str, dict] = {}

HELP_TEXT = """指令说明：

【快速生成】
  解说 <热搜话题>    → 自动写解说稿 + 生成视频
  科普 <知识主题>    → 查资料 + 写科普稿 + 生成视频
  故事 <情感主题>    → 写情感故事 + 配氛围画面
  奇闻 <猎奇话题>    → 写猎奇文案 + 悬疑画面
  观点 <社会话题>    → 写观点输出 + 生成视频

【通用创作】
  任务 <主题>        → 用当前风格生成5条解说稿方案

【改编模式】
  改编 <B站链接>     → 多帧理解视频内容 → VLM 改编（推荐）
  改编 <本地路径>    → 服务器本地视频文件 → VLM 改编
  （直接上传视频到聊天）→ 自动识别并 VLM 改编
  模仿 <文字或链接>  → 参考爆款结构改编
  爆改 <链接或文字>  → 基于原内容深度二创（不是换皮）
  改写 <原文>        → 真正的内容改写（换角度重写）

【热搜联动】
  热搜               → 展示最新热搜
  热门               → AI 推荐 Top 5 选题
  热搜 3             → 直接用第3条热搜生成解说视频
  刷新热搜           → 强制刷新热搜数据
  批量 5             → 批量入队生成 5 条热门解说视频
  定时 3             → 每日自动产出 3 条视频
  定时关             → 关闭每日自动产出
  触发定时           → 立即执行一次每日自动产出
  数据 <视频ID> ...   → 手动录入播放/完播/互动数据
  爆了 <视频ID>      → 自动裂变 5 条变体
  记忆提炼           → 基于已录入数据生成待审核运营规律
  记忆通过 <ID>      → 通过一条记忆提案并注入后续 prompt

【角色 IP】
  角色               → 查看可用角色列表
  角色 <角色名>      → 切换当前角色

【风格切换】
  风格               → 查看/切换内容垂类模板

【创作 Skill】
  Skill              → 查看可用 Skill
  Skill 电影         → 切换当前创作 Skill

【生成视频】
  确认               → 生成推荐方案1
  确认 2             → 生成第2条方案

【管理】
  计划 / 帮助
"""

# 当前会话使用的风格模板名（后续迁移到数据库/内存）
_current_style: str = "hot_news_commentary"
_current_character: str = ""
_current_skill: str = ""

# 垂类指令→模板映射
_VERTICAL_CMD_MAP: dict[str, str] = {
    "解说": "hot_news_commentary",
    "科普": "knowledge_explainer",
    "故事": "emotional_story",
    "奇闻": "curiosity_facts",
    "观点": "social_insight",
}


def _get_style() -> StyleTemplate:
    return get_template(_current_style)


def _save_session(chat_id: str, **kwargs) -> None:
    if chat_id not in _session_store:
        _session_store[chat_id] = {}
    _session_store[chat_id].update(kwargs)


def _get_session(chat_id: str) -> dict | None:
    return _session_store.get(chat_id)


def _split_caption_text(text: str, max_chars: int = 15) -> list[str]:
    """Split Chinese narration into short burn-in subtitle chunks."""
    text = re.sub(r"\s+", "", to_simplified_zh(str(text or "").strip()))
    if not text:
        return []

    chunks: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in "，。！？；、,.!?;" or len(buf) >= max_chars:
            piece = buf.strip("，。！？；、,.!?; ")
            if piece:
                chunks.append(piece)
            buf = ""
    tail = buf.strip("，。！？；、,.!?; ")
    if tail:
        chunks.append(tail)
    return chunks


def _build_timed_captions_from_text(text: str, total_duration_sec: float, max_chars: int = 15) -> list[CaptionItem]:
    chunks = _split_caption_text(text, max_chars=max_chars)
    if not chunks or total_duration_sec <= 0:
        return []

    total_chars = max(1, sum(len(c) for c in chunks))
    cursor = 0.0
    items: list[CaptionItem] = []
    min_duration = 0.85
    for idx, chunk in enumerate(chunks):
        if idx == len(chunks) - 1:
            end = total_duration_sec
        else:
            duration = max(min_duration, total_duration_sec * len(chunk) / total_chars)
            end = min(total_duration_sec, cursor + duration)
        if end - cursor >= 0.2:
            items.append(CaptionItem(text=chunk, start_sec=round(cursor, 2), end_sec=round(end, 2)))
        cursor = end
        if cursor >= total_duration_sec:
            break
    return items


def _build_timed_captions_from_plan(clips: list[dict], fallback: list[str] | None = None) -> list[CaptionItem]:
    """Use evaluation clip timings as the primary subtitle source.

    This keeps subtitle pacing aligned with the actual narration plan instead of
    evenly spreading a few short slogan captions across the full video duration.
    """
    items: list[CaptionItem] = []
    cursor = 0.0

    for clip in clips:
        text = to_simplified_zh((clip.get("narration_segment") or clip.get("scene_summary") or "").strip())
        duration = float(clip.get("duration_sec") or 0)
        if not text or duration <= 0:
            continue
        chunks = _split_caption_text(text)
        if chunks:
            per = duration / len(chunks)
            for idx, chunk in enumerate(chunks):
                items.append(
                    CaptionItem(
                        text=chunk,
                        start_sec=round(cursor + idx * per, 2),
                        end_sec=round(cursor + (idx + 1) * per, 2),
                    )
                )
        else:
            items.append(
                CaptionItem(
                    text=text,
                    start_sec=round(cursor, 2),
                    end_sec=round(cursor + duration, 2),
                )
            )
        cursor += duration

    if items:
        return items

    fallback = fallback or []
    if not fallback:
        return []

    total = max(float(cursor), float(len(fallback)))
    per = total / len(fallback)
    return [
        CaptionItem(
            text=text.strip()[:15],
            start_sec=round(i * per, 2),
            end_sec=round((i + 1) * per, 2),
        )
        for i, text in enumerate(fallback)
        if text and text.strip()
    ]


def _rebuild_timed_captions_from_narration(
    clips_spec: list[dict],
    narration_text: str,
    voiceover_duration_sec: float,
) -> list[CaptionItem]:
    """统一从 narration 重建字幕，绝不用 LLM captions。"""
    items = _build_timed_captions_from_plan(clips_spec)
    if items:
        return items
    if narration_text and voiceover_duration_sec > 0:
        return _build_timed_captions_from_text(
            narration_text, total_duration_sec=voiceover_duration_sec
        )
    return []


def _safe_visual_prompt(prompt: str, *, fallback: str = "") -> str:
    return sanitize_visual_prompt(prompt, fallback=fallback)


def _caption_burn_enabled() -> bool:
    return bool(get_settings().enable_burn_captions)


def _classify_error(exc: Exception) -> str:
    """Map runtime errors into P9 fail_records error_code buckets."""
    msg = str(exc).lower()
    type_name = type(exc).__name__
    if "timeout" in msg and ("tts" in msg or "websocket" in msg):
        return "TTS_TIMEOUT"
    if "kling" in msg or "1201" in msg or "image2video" in msg or "可灵" in str(exc):
        return "KLING_FAILED"
    if "drift" in msg or "av_sync" in msg or "AVDriftTooLargeError" in type_name:
        return "AV_DRIFT"
    if "text" in msg and "artifact" in msg:
        return "TEXT_LIKE_DETECTED"
    if "narration" in msg and ("超过" in str(exc) or "too long" in msg):
        return "PROMPT_TOO_LONG"
    return "OTHER"


async def _record_fail_guarded(
    cid: str,
    *,
    stage: str,
    exc: Exception,
    session_id: str | None = None,
    error_code: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Best-effort P9 fail_records write; never blocks video generation."""
    try:
        gs_id = session_id or (_get_session(cid) or {}).get("generation_session_id")
        await record_fail(
            session_id=gs_id,
            stage=stage,
            error_code=error_code or _classify_error(exc),
            error_message=str(exc),
            metadata=metadata,
        )
    except Exception as fail_exc:
        log.warning("[端到端] P9 record_fail 失败（不阻断）: %s", fail_exc)


async def _attempt_av_rescue_guarded(
    cid: str,
    *,
    mixed_path: str,
    video_path: str,
    voiceover_path: str,
    narration_text: str,
    drift_err: AVDriftTooLargeError,
    output_dir: str,
    voice_key: str,
    storyboard_id: str | None = None,
) -> str | None:
    """Try D41-C AV rescue and notify Feishu. Return rescued mixed path or None."""
    log.info(
        "[av_rescue] triggered drift=%+.2fs video=%.2fs audio=%.2fs",
        drift_err.report.drift_sec,
        drift_err.report.video_sec,
        drift_err.report.voiceover_sec,
    )
    rescue = await attempt_rescue(
        mixed_path=mixed_path,
        video_path=video_path,
        voiceover_path=voiceover_path,
        narration_text=narration_text,
        drift_sec=drift_err.report.drift_sec,
        output_dir=output_dir,
        tts_voice_key=voice_key,
        storyboard_id=storyboard_id,
    )
    if rescue.success and rescue.new_mixed_path:
        await send_text(
            cid,
            (
                f"🛟 自动救援成功（{rescue.strategy.value}）："
                f"漂移 {drift_err.report.drift_sec:+.2f}s → {rescue.new_drift_sec:+.2f}s，"
                f"成本 ¥{rescue.cost_cny:.2f}"
            ),
        )
        return rescue.new_mixed_path
    await send_text(cid, f"🔴 救援失败：{rescue.message}")
    return None


async def _store_storyboard_anchors_guarded(plan_id: str | None, anchors: StoryAnchors) -> None:
    """Best-effort D41-A anchors persistence; never blocks generation."""
    if not plan_id or not anchors or (not anchors.characters and not anchors.scenes):
        return
    try:
        from sqlalchemy import or_, select

        from db.connection import get_session_factory
        from db.models import Storyboard

        async with get_session_factory()() as session:
            result = await session.execute(
                select(Storyboard)
                .where(or_(Storyboard.id == plan_id, Storyboard.plan_id == plan_id))
                .limit(1)
            )
            storyboard = result.scalar_one_or_none()
            if storyboard is None:
                log.warning("[anchors] storyboard not found for plan_id=%s; skip anchors persist", plan_id)
                return
            storyboard.anchors = anchors.model_dump(mode="json")
            await session.commit()
            log.info("[anchors] persisted storyboard anchors plan_id=%s", plan_id)
    except Exception as exc:
        log.warning("[anchors] persist failed, continue without blocking: %s", exc)


async def _send_final_score_prompt(cid: str, gs_id: str) -> None:
    """Ask user for a 1-10 final score and keep the pending session id in memory."""
    _save_session(cid, pending_final_score_session_id=gs_id)
    await send_text(
        cid,
        "视频已完成。请给本次效果打 1-10 分（10 最好）："
        "\n - 直接回数字（如 `8`）"
        "\n - 或 `评分 8`"
        "\n - >=6 分自动写入偏好库，下次类似生成会参考",
    )


def _shot_map_from_visual(visual: dict) -> dict[int, dict]:
    shots = visual.get("shots") if isinstance(visual, dict) else None
    if not isinstance(shots, list):
        return {}
    result: dict[int, dict] = {}
    for idx, shot in enumerate(shots, start=1):
        if not isinstance(shot, dict):
            continue
        try:
            shot_no = int(shot.get("shot_no") or idx)
        except (TypeError, ValueError):
            shot_no = idx
        result[shot_no] = shot
    return result


_CAMERA_TYPES = {"push_in", "pull_out", "pan_left", "pan_right", "tilt_up", "tilt_down", "orbit", "static"}


def _shot_template_map(style_name: str) -> dict[int, dict]:
    try:
        shots = chains.get_shot_template(style_name)
    except Exception as exc:
        log.warning("[端到端] 分镜模板读取失败: %s", exc)
        return {}
    result: dict[int, dict] = {}
    for idx, shot in enumerate(shots, start=1):
        if not isinstance(shot, dict):
            continue
        try:
            shot_no = int(shot.get("shot_no") or idx)
        except (TypeError, ValueError):
            shot_no = idx
        result[shot_no] = shot
    return result


def _normalize_camera_control(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None

    camera_type = str(value.get("type") or "").strip()
    if camera_type not in _CAMERA_TYPES:
        return None

    raw_config = value.get("config")
    if not isinstance(raw_config, dict):
        raw_config = {}

    config: dict[str, int] = {}
    for key in ("horizontal", "vertical", "zoom"):
        try:
            num = int(float(raw_config.get(key, 0)))
        except (TypeError, ValueError):
            num = 0
        config[key] = max(-10, min(10, num))

    return {"type": camera_type, "config": config}


@router.post("/feishu")
async def webhook(request: Request, bg: BackgroundTasks):
    try:
        body = await request.json()
    except Exception as e:
        log.error("[Webhook] 解析body失败: %s", e)
        return {"ok": False}

    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}

    event = body.get("event", {})
    message = event.get("message", {})
    msg_type = message.get("message_type")
    cid = message.get("chat_id")
    raw_content = message.get("content", "{}")
    try:
        content_obj = json.loads(raw_content)
    except Exception:
        content_obj = {}

    log.info("[Webhook] msg_type=%s cid=%s content_keys=%s", msg_type, cid, list(content_obj.keys()))

    # ── 飞书视频/文件上传 → 自动改编 ──
    # 飞书视频消息类型为 "media"，文件为 "file"，兼容旧版 "video"
    if msg_type in ("media", "video", "file"):
        if not cid:
            return {"ok": True}
        # media: file_key / video_key；file: file_key
        file_key = (content_obj.get("file_key")
                    or content_obj.get("video_key")
                    or "")
        msg_id = message.get("message_id", "")
        log.info("[Webhook] 收到媒体消息 type=%s file_key=%s msg_id=%s", msg_type, file_key[:20] if file_key else "", msg_id)
        if file_key and msg_id:
            if _sem.locked():
                bg.add_task(send_text, cid, "有任务进行中，请稍候...")
                return {"ok": True}
            async def _handle_feishu_video():
                async with _sem:
                    try:
                        await _run_rewrite_vlm_from_feishu(cid, msg_id, file_key, msg_type)
                    except Exception as e:
                        log.error("[feishu_video] %s", e, exc_info=True)
                        await send_text(cid, f"视频分析失败：{str(e)[:200]}")
            bg.add_task(_handle_feishu_video)
        else:
            log.warning("[Webhook] 媒体消息缺少 file_key 或 msg_id，忽略")
        return {"ok": True}

    if msg_type != "text":
        return {"ok": True}

    try:
        text = content_obj["text"].strip()
    except Exception:
        return {"ok": True}

    try:
        from core.scheduler import runtime_set
        await runtime_set("default_chat_id", cid)
        await runtime_set("last_active_chat_id", cid)
    except Exception:
        pass

    log.info("[Webhook] text=%s", text[:80])

    # P9: final score replies have the highest priority after we prompt the user.
    session = _get_session(cid) or {}
    pending_score_sid = session.get("pending_final_score_session_id")
    if pending_score_sid:
        score = parse_score_reply(text)
        if score is not None:
            try:
                outcome: ScoreOutcome = await record_final_score(pending_score_sid, score)
                await send_text(cid, outcome.to_feishu_line())
            except Exception as e:
                log.warning("[端到端] P9 record_final_score 失败: %s", e)
                await send_text(cid, f"评分记录失败：{e}")
            session.pop("pending_final_score_session_id", None)
            _save_session(cid, **session)
            return {"ok": True}

    # ── 轻量指令 ──
    if await _handle_light_command(cid, text, bg):
        return {"ok": True}

    # ── 确认（触发端到端视频生成）──
    session = _get_session(cid)
    if session and session.get("pending_visual_clip_review"):
        if _sem.locked():
            bg.add_task(send_text, cid, "有任务进行中，请稍候")
            return {"ok": True}

        async def handle_visual_clip_review():
            async with _sem:
                try:
                    handled = await _handle_visual_clip_review(cid, text)
                    if not handled:
                        await send_text(cid, "请回复：1.继续；或 2.重新生成: 你的改动意见；或 3.取消")
                except Exception as e:
                    log.error("[visual_review] %s", e, exc_info=True)
                    await _record_fail_guarded(cid, stage="clip", exc=e)
                    await send_text(cid, f"片段审核处理失败：{str(e)[:200]}")

        bg.add_task(handle_visual_clip_review)
        return {"ok": True}

    if text == "确认" or text.startswith("确认 "):
        if _sem.locked():
            bg.add_task(send_text, cid, "有任务进行中，请稍候")
            return {"ok": True}

        async def confirm_chain():
            async with _sem:
                try:
                    await _handle_confirm(cid, text)
                except Exception as e:
                    log.error("[confirm] %s", e, exc_info=True)
                    await _record_fail_guarded(cid, stage="session", exc=e)
                    await send_text(cid, f"生成失败：{str(e)[:200]}")

        bg.add_task(confirm_chain)
        return {"ok": True}

    # ── 龙虾链（占 Semaphore）──
    if _sem.locked():
        bg.add_task(send_text, cid, "有任务进行中，请稍候（发「计划」查看进度）")
        return {"ok": True}

    async def guarded_chain():
        async with _sem:
            try:
                await _dispatch_chain(cid, text)
            except Exception as e:
                log.error("[chain] %s", e, exc_info=True)
                await _record_fail_guarded(cid, stage="session", exc=e)
                await send_text(cid, f"系统错误：{str(e)[:100]}")

    bg.add_task(guarded_chain)
    return {"ok": True}


async def _handle_light_command(cid: str, text: str, bg: BackgroundTasks) -> bool:
    global _current_style, _current_character, _current_skill

    if text in ("帮助", "help", "?", "？"):
        bg.add_task(send_text, cid, HELP_TEXT)
        return True

    if text in ("Skill", "skill", "技能"):
        session = _get_session(cid) or {}
        active_skill = session.get("current_skill", _current_skill)
        bg.add_task(send_text, cid, format_creative_skills_for_feishu(active_skill))
        return True

    if text.startswith(("Skill ", "skill ", "技能 ")):
        name = text.split(None, 1)[1].strip()
        skill = get_creative_skill(name)
        if not skill:
            bg.add_task(
                send_text,
                cid,
                f"Skill「{name}」不存在。\n\n{format_creative_skills_for_feishu(_current_skill)}",
            )
            return True

        _current_skill = skill.id
        try:
            get_template(skill.default_prompt_style)
            _current_style = skill.default_prompt_style
        except KeyError as exc:
            log.warning("[creative_skills] default style missing for %s: %s", skill.id, exc)

        _save_session(
            cid,
            current_skill=skill.id,
            style_name=_current_style,
            skill_intensity=skill.default_intensity,
            skill_shot_template_key=skill.shot_template_key,
            skill_prompt_director_config_key=skill.prompt_director_config_key,
        )
        bg.add_task(
            send_text,
            cid,
            (
                f"Skill 已切换为：{skill.name}\n"
                f"默认风格：{skill.default_prompt_style}\n"
                f"强度：{skill.default_intensity}\n"
                f"下一次生成会按这个 Skill 起步。"
            ),
        )
        return True

    if text == "风格":
        names = list_template_names()
        msg = f"可用风格模板：\n" + "\n".join(
            f"  {'> ' if n == _current_style else '  '}{n}" for n in names
        )
        msg += f"\n\n当前：{_current_style}\n切换：发「风格 <模板名>」"
        bg.add_task(send_text, cid, msg)
        return True

    if text.startswith("风格 "):
        name = text.split(None, 1)[1].strip()
        try:
            get_template(name)
            _current_style = name
            bg.add_task(send_text, cid, f"风格已切换为：{name}")
        except KeyError as e:
            bg.add_task(send_text, cid, str(e))
        return True

    # ── Phase 3.5: 角色 IP 指令 ──
    if text == "角色":
        chars = list_characters()
        if not chars:
            bg.add_task(send_text, cid, "暂无可用角色，请检查 config/characters.yaml")
        else:
            active = _current_character or "(自动选择)"
            lines = [f"可用角色 IP（当前：{active}）：\n"]
            for c in chars:
                marker = "> " if c.key == _current_character or c.display_name == _current_character else "  "
                ref_status = "有参考图" if c.best_ref_path() else "待生成参考图"
                lines.append(f"  {marker}{c.display_name}（{c.key}）— {ref_status}")
                lines.append(f"      {c.description[:40]}...")
            lines.append(f"\n切换：发「角色 <角色名>」")
            bg.add_task(send_text, cid, "\n".join(lines))
        return True

    if text.startswith("角色 "):
        name = text.split(None, 1)[1].strip()
        char = get_character(name)
        if char:
            _current_character = char.key
            ref_info = f"（参考图：{'已就绪' if char.best_ref_path() else '待生成'}）"
            bg.add_task(send_text, cid, f"角色已切换为：{char.display_name} {ref_info}")
        else:
            chars = list_characters()
            names = ", ".join(f"{c.display_name}({c.key})" for c in chars)
            bg.add_task(send_text, cid, f"角色 '{name}' 不存在。可用角色：{names}")
        return True

    # ── Phase 3: 热搜指令 ──
    if text in ("热搜", "热门话题", "刷新热搜"):
        bg.add_task(_handle_trending, cid, force_refresh=(text == "刷新热搜"))
        return True

    if text in ("热门", "推荐", "选题"):
        bg.add_task(_handle_recommend, cid)
        return True

    if text == "触发定时":
        bg.add_task(_handle_trigger_daily_batch, cid)
        return True

    if text in ("定时关", "关闭定时"):
        bg.add_task(_handle_schedule_toggle, cid, False, 0)
        return True

    if text == "批量":
        bg.add_task(_handle_batch, cid, 5)
        return True

    if text.startswith("批量 "):
        try:
            n = int(text.split(None, 1)[1].strip())
        except Exception:
            bg.add_task(send_text, cid, "批量数量格式不对，示例：批量 5")
            return True
        bg.add_task(_handle_batch, cid, n)
        return True

    if text.startswith("定时 "):
        try:
            n = int(text.split(None, 1)[1].strip())
        except Exception:
            bg.add_task(send_text, cid, "定时数量格式不对，示例：定时 3")
            return True
        bg.add_task(_handle_schedule_toggle, cid, True, n)
        return True

    if text.startswith("数据 "):
        payload = text.split(None, 1)[1].strip()
        bg.add_task(_handle_metrics_input, cid, payload)
        return True

    if text.startswith("爆了 "):
        video_id = text.split(None, 1)[1].strip()
        bg.add_task(_handle_viral_trigger, cid, video_id)
        return True

    if text == "记忆提炼":
        bg.add_task(_handle_memory_dream, cid)
        return True

    if text.startswith("记忆通过 "):
        proposal_id = text.split(None, 1)[1].strip()
        bg.add_task(_handle_memory_approve, cid, proposal_id)
        return True

    # ── Phase 3: 序号选择（热门推荐后回复数字） ──
    if text.isdigit() and 1 <= int(text) <= 30:
        bg.add_task(_handle_topic_select, cid, int(text))
        return True

    return False


async def _handle_trending(cid: str, force_refresh: bool = False) -> None:
    """Fetch and display hot topics from all platforms."""
    try:
        from db.connection import get_session_factory
        from layers.L1_trending.fetcher import fetch_all, format_trending_for_feishu

        async with get_session_factory()() as session:
            if force_refresh:
                await send_text(cid, "正在抓取最新热搜...")
                await fetch_all(session)
                await session.commit()
            msg, topic_list = await format_trending_for_feishu(session)
            if topic_list:
                _save_session(cid, trending_topics=topic_list)
            await send_text(cid, msg)
    except Exception as e:
        log.error("[trending] %s", e, exc_info=True)
        await send_text(cid, f"热搜获取失败：{str(e)[:100]}")


async def _handle_recommend(cid: str) -> None:
    """AI-powered topic recommendations based on current trending."""
    try:
        from db.connection import get_session_factory
        from layers.L1_trending.analyzer import analyze_and_recommend, format_recommendations

        await send_text(cid, "正在分析热搜，生成选题推荐...")
        async with get_session_factory()() as session:
            recs = await analyze_and_recommend(session, limit=5)
            if recs:
                _save_session(cid, recommendations=recs)
            msg = format_recommendations(recs)
            await send_text(cid, msg)
    except Exception as e:
        log.error("[recommend] %s", e, exc_info=True)
        await send_text(cid, f"推荐生成失败：{str(e)[:100]}")


async def _handle_topic_select(cid: str, choice: int) -> None:
    """User replied with a number after seeing trending or recommendations."""
    session_data = _get_session(cid)
    if not session_data:
        await send_text(cid, "没有可选的列表，请先发「热搜」或「热门」。")
        return

    # 优先匹配热门推荐（有 AI 分析的切入角度）
    recommendations = session_data.get("recommendations")
    if recommendations and choice <= len(recommendations):
        rec = recommendations[choice - 1]
        topic = rec.get("title", "")
        angle = rec.get("angle", "")
        theme = topic
        if angle:
            theme += f"（切入角度：{angle}）"
        await send_text(cid, f"已选择推荐 {choice}：{topic}\n用「热搜解说」模式开始创作...")
        news_style = get_template("hot_news_commentary")
        await _run_vertical(cid, theme, news_style, "hot_news_commentary")
        return

    # 其次匹配热��列表
    trending = session_data.get("trending_topics")
    if trending and choice <= len(trending):
        item = trending[choice - 1]
        topic = item.get("title", "")
        await send_text(cid, f"已选择热搜 {choice}：{topic}\n用「热搜解说」模式开始创作...")
        news_style = get_template("hot_news_commentary")
        await _run_vertical(cid, topic, news_style, "hot_news_commentary")
        return

    await send_text(cid, "序号超出范围，请先发「热搜」或「热门」获取列表。")


async def _notify_video_ready(cid: str) -> None:
    """Push a Feishu message with the video details for manual publishing."""
    from layers.L6_distribution.publisher import build_publish_card

    session_data = _get_session(cid)
    if not session_data or "last_video_path" not in session_data:
        return

    msg = build_publish_card(
        title=session_data.get("last_title", ""),
        video_path=session_data["last_video_path"],
        tags=session_data.get("last_tags", []),
        cover_path=session_data.get("last_cover_path"),
    )
    await send_text(cid, msg)


async def _handle_batch(cid: str, count: int) -> None:
    from db.connection import get_session_factory
    from layers.L1_trending.analyzer import analyze_and_recommend
    from layers.L1_trending.fetcher import fetch_all
    from core.scheduler import enqueue_job

    count = max(1, min(10, count))
    await send_text(cid, f"开始批量模式：准备从热搜里选 {count} 个题目入队生成...")

    async with get_session_factory()() as session:
        recs = await analyze_and_recommend(session, limit=count)
        if not recs:
            await send_text(cid, "当前没有可用推荐，先刷新热搜再重试。")
            await fetch_all(session)
            await session.commit()
            recs = await analyze_and_recommend(session, limit=count)

    if not recs:
        await send_text(cid, "批量模式失败：热搜推荐为空。")
        return

    job_ids = []
    lines = [f"批量任务已入队（{len(recs)} 条）：\n"]
    for idx, rec in enumerate(recs, start=1):
        topic = rec.get("title", "")
        angle = rec.get("angle", "")
        theme = topic if not angle else f"{topic}（切入角度：{angle}）"
        job_id = await enqueue_job("task_generate_video", cid, theme, "hot_news_commentary", "batch", 1)
        job_ids.append(job_id)
        lines.append(f"{idx}. {topic}  → {job_id[:8]}")
    await send_text(cid, "\n".join(lines))


async def _handle_schedule_toggle(cid: str, enabled: bool, count: int) -> None:
    from core.scheduler import runtime_set

    if enabled:
        count = max(1, min(10, count or 3))
        await runtime_set("daily_batch_enabled", "1")
        await runtime_set("daily_batch_size", str(count))
        await runtime_set("default_chat_id", cid)
        await send_text(cid, f"已开启每日自动产出：每天 09:00 自动生成 {count} 条热门解说视频。")
    else:
        await runtime_set("daily_batch_enabled", "0")
        await send_text(cid, "已关闭每日自动产出。")


async def _handle_trigger_daily_batch(cid: str) -> None:
    from core.scheduler import enqueue_job, runtime_set

    await runtime_set("default_chat_id", cid)
    job_id = await enqueue_job("task_daily_batch")
    await send_text(cid, f"已触发一次每日自动产出任务：{job_id[:8]}")


def _parse_rate_token(value: str) -> float:
    value = value.strip()
    if value.endswith("%"):
        return round(float(value[:-1]) / 100.0, 4)
    num = float(value)
    return round(num / 100.0, 4) if num > 1 else round(num, 4)


def _parse_metrics_payload(payload: str) -> tuple[str, dict]:
    parts = payload.split()
    if not parts:
        raise ValueError("格式应为：数据 <视频ID> 播放量=10000 完播率=35% 互动率=7%")
    video_id = parts[0].strip()
    metrics: dict = {
        "views": 0,
        "completion_rate": None,
        "engagement_rate": None,
        "likes": 0,
        "comments": 0,
        "shares": 0,
        "note": "",
    }
    alias = {
        "播放量": "views",
        "播放": "views",
        "完播率": "completion_rate",
        "互动率": "engagement_rate",
        "点赞": "likes",
        "评论": "comments",
        "分享": "shares",
        "备注": "note",
    }
    for token in parts[1:]:
        if "=" not in token:
            continue
        k, v = token.split("=", 1)
        key = alias.get(k.strip(), k.strip())
        val = v.strip()
        if key in {"completion_rate", "engagement_rate"}:
            metrics[key] = _parse_rate_token(val)
        elif key in {"views", "likes", "comments", "shares"}:
            metrics[key] = int(val.replace(",", ""))
        elif key == "note":
            metrics[key] = val
    return video_id, metrics


async def _record_video_output(
    *,
    chat_id: str,
    source: str,
    style_name: str,
    theme: str,
    title: str,
    narration: str,
    tags: list[str] | None,
    video_path: str,
    cover_path: str | None,
    quality_score: float | None = None,
    plan_id: str | None = None,
) -> str:
    from db.connection import get_session_factory
    from db.models import VideoRecord

    video_id = uuid.uuid4().hex[:10].upper()
    async with get_session_factory()() as session:
        session.add(
            VideoRecord(
                id=video_id,
                plan_id=plan_id,
                chat_id=chat_id,
                source=source,
                style_name=style_name,
                theme=theme,
                title=title,
                narration=narration,
                tags=tags or [],
                video_path=video_path,
                cover_path=cover_path or "",
                quality_score=quality_score,
            )
        )
        await session.commit()
    return video_id


async def _handle_metrics_input(cid: str, payload: str) -> None:
    from db.connection import get_session_factory
    from db.models import VideoMetric, VideoRecord

    try:
        video_id, metrics = _parse_metrics_payload(payload)
    except Exception as e:
        await send_text(cid, f"数据录入格式错误：{e}")
        return

    async with get_session_factory()() as session:
        video = await session.get(VideoRecord, video_id)
        if not video:
            await send_text(cid, f"视频ID不存在：{video_id}")
            return
        metric = VideoMetric(video_id=video_id, **metrics)
        session.add(metric)
        views = metrics.get("views", 0)
        completion_rate = metrics.get("completion_rate") or 0
        engagement_rate = metrics.get("engagement_rate") or 0
        if views >= 10000 and completion_rate >= 0.3 and engagement_rate >= 0.05:
            video.is_viral = True
        await session.commit()

    viral_text = "，已标记为爆款" if views >= 10000 and completion_rate >= 0.3 and engagement_rate >= 0.05 else ""
    await send_text(
        cid,
        f"数据已录入：{video_id}\n播放量={views} 完播率={completion_rate:.0%} 互动率={engagement_rate:.0%}{viral_text}",
    )


async def _handle_viral_trigger(cid: str, video_id: str) -> None:
    from db.connection import get_session_factory
    from db.models import VideoRecord
    from layers.L2_creative.structure_library import build_structure_library
    from layers.L2_creative.variant_generator import format_variants, generate_variants
    from core.scheduler import enqueue_job

    async with get_session_factory()() as session:
        video = await session.get(VideoRecord, video_id)
        if not video:
            await send_text(cid, f"视频ID不存在：{video_id}")
            return
        structures = await build_structure_library(session, limit=10)

    await send_text(cid, f"开始裂变爆款 {video_id}：{video.title or video.theme}")
    variants = await generate_variants(
        seed_title=video.title,
        seed_theme=video.theme,
        style_name=video.style_name,
        narration=video.narration,
        structure_hints=structures,
        count=5,
    )
    if not variants:
        await send_text(cid, "未生成可用裂变变体。")
        return

    await send_text(cid, format_variants(variants))
    lines = ["裂变任务已入队："]
    for idx, item in enumerate(variants, start=1):
        theme = item.get("theme") or f"{video.theme} 变体{idx}"
        style_name = item.get("style_name") or video.style_name or "hot_news_commentary"
        job_id = await enqueue_job("task_generate_video", cid, theme, style_name, "variant", 1)
        lines.append(f"{idx}. {theme} → {job_id[:8]}")
    await send_text(cid, "\n".join(lines))


async def _handle_memory_dream(cid: str) -> None:
    """Generate memory proposals and store them for explicit human approval."""
    try:
        from core.dreaming_scheduler import (
            MemoryProposal,
            format_memory_proposals,
            propose_memory_updates,
        )
        from core.scheduler import runtime_set
        from db.connection import get_session_factory

        async with get_session_factory()() as session:
            result = await propose_memory_updates(session, force=True)
        if not result.triggered or not result.proposals:
            await send_text(cid, f"暂无可写入记忆的规律：{result.reason}")
            return

        payload = [
            {
                "id": p.id,
                "style_name": p.style_name,
                "insight": p.insight,
                "evidence": p.evidence,
                "prompt_rule": p.prompt_rule,
                "confidence": p.confidence,
            }
            for p in result.proposals
        ]
        await runtime_set("pending_memory_proposals", json.dumps(payload, ensure_ascii=False))
        await send_text(cid, format_memory_proposals(result.proposals))
    except Exception as e:
        log.error("[memory_dream] %s", e, exc_info=True)
        await send_text(cid, f"记忆提炼失败：{str(e)[:160]}")


async def _handle_memory_approve(cid: str, proposal_id: str) -> None:
    """Append one pending proposal to LONG_TERM_MEMORY after human approval."""
    try:
        from core.dreaming_scheduler import MemoryProposal, append_approved_memory
        from core.scheduler import runtime_get, runtime_set

        raw = await runtime_get("pending_memory_proposals")
        if not raw:
            await send_text(cid, "没有待审核的记忆提案。先发「记忆提炼」。")
            return
        items = json.loads(raw)
        matched = None
        for item in items:
            if str(item.get("id", "")).upper() == proposal_id.upper():
                matched = item
                break
        if not matched:
            await send_text(cid, f"未找到记忆提案：{proposal_id}")
            return

        proposal = MemoryProposal(
            id=matched["id"],
            style_name=matched.get("style_name", "global"),
            insight=matched.get("insight", ""),
            evidence=matched.get("evidence", ""),
            prompt_rule=matched.get("prompt_rule", ""),
            confidence=float(matched.get("confidence", 0.5)),
        )
        append_approved_memory(proposal)
        remaining = [item for item in items if str(item.get("id", "")).upper() != proposal_id.upper()]
        await runtime_set("pending_memory_proposals", json.dumps(remaining, ensure_ascii=False))
        await send_text(cid, f"已写入长期记忆：{proposal.prompt_rule}")
    except Exception as e:
        log.error("[memory_approve] %s", e, exc_info=True)
        await send_text(cid, f"记忆写入失败：{str(e)[:160]}")


async def _dispatch_chain(cid: str, text: str) -> None:
    session = _get_session(cid) or {}
    active_skill = session.get("current_skill", _current_skill)
    style_name = session.get("style_name", _current_style)
    style = get_template(style_name)

    # ── 垂类快捷指令（解说/科普/故事/奇闻/观点）──
    for cmd, template_name in _VERTICAL_CMD_MAP.items():
        if text.startswith(f"{cmd} ") or text.startswith(f"{cmd}　"):
            theme = text.split(None, 1)[1].strip()
            if active_skill:
                await _run_vertical(cid, theme, style, style.name)
            else:
                vertical_style = get_template(template_name)
                await _run_vertical(cid, theme, vertical_style, template_name)
            return

    if text.startswith("改编 ") or text.startswith("改编　"):
        src = text.split(None, 1)[1].strip()
        await _run_rewrite_vlm(cid, src, style)
    elif text.startswith("改写 ") or text.startswith("改写　"):
        src = text.split(None, 1)[1].strip()
        await _run_rewrite(cid, src, style)
    elif text.startswith("爆改 ") or text.startswith("爆改\u3000"):
        src = text.split(None, 1)[1].strip()
        await _run_baogai(cid, src, style)
    elif text.startswith("模仿 ") or text.startswith("模仿\u3000"):
        ref = text.split(None, 1)[1].strip()
        await _run_reference(cid, ref, style)
    elif any(kw in text for kw in ["任务", "出击", "创意", "行动"]):
        await _run_creative(cid, text, style)
    else:
        await send_text(cid, HELP_TEXT)


async def _run_creative(cid: str, theme: str, style: StyleTemplate) -> None:
    await send_text(cid, f"创意链启动（风格：{style.display_name}）...")
    scripts = await chains.lobster_creative(theme, style)
    ok, reason = content_guard(scripts)
    if not ok:
        await send_text(cid, f"内容被拦截：{reason}")
        return

    review = chains.lobster_review(scripts, style)
    await send_long(cid, f"解说稿审核完成：\n{review}")

    evaluation = await chains.lobster_evaluate(review)
    if not evaluation.get("plans"):
        raise RuntimeError("评估链未返回可用方案")
    msg, cost = chains.format_evaluation(evaluation)
    await send_text(cid, msg)

    _save_session(cid, scripts=review, evaluation=evaluation, style_name=_current_style, current_theme=theme, source="creative")


async def _run_reference(cid: str, ref_input: str, style: StyleTemplate) -> None:
    await send_text(cid, f"参考改编启动（风格：{style.display_name}）...")
    scripts = await chains.lobster_reference(ref_input, style)
    ok, reason = content_guard(scripts)
    if not ok:
        await send_text(cid, f"内容被拦截：{reason}")
        return

    evaluation = await chains.lobster_evaluate(scripts)
    if not evaluation.get("plans"):
        raise RuntimeError("评估链未返回可用方案")
    msg, cost = chains.format_evaluation(evaluation)
    await send_text(cid, msg)

    _save_session(cid, scripts=scripts, evaluation=evaluation, style_name=_current_style, current_theme=ref_input, source="reference")


async def _run_baogai(cid: str, source: str, style: StyleTemplate) -> None:
    await send_text(cid, f"爆改链启动（风格：{style.display_name}）...")
    scripts = await chains.lobster_baogai(source, style)
    ok, reason = content_guard(scripts)
    if not ok:
        await send_text(cid, f"爆改内容被拦截：{reason}")
        return

    evaluation = await chains.lobster_evaluate(scripts)
    if not evaluation.get("plans"):
        raise RuntimeError("评估链未返回可用方案")
    msg, cost = chains.format_evaluation(evaluation)
    await send_text(cid, msg)

    _save_session(cid, scripts=scripts, evaluation=evaluation, style_name=_current_style, current_theme=source, source="baogai")


async def _run_vertical(cid: str, theme: str, style: StyleTemplate, vertical_key: str) -> None:
    await send_text(cid, f"「{style.display_name}」模式启动，主题：{theme}...")
    scripts = await chains.lobster_vertical(theme, style, vertical_key)
    ok, reason = content_guard(scripts)
    if not ok:
        await send_text(cid, f"内容被拦截：{reason}")
        return

    review = chains.lobster_review(scripts, style)
    await send_long(cid, f"解说稿审核完成：\n{review}")

    evaluation = await chains.lobster_evaluate(review)
    if not evaluation.get("plans"):
        raise RuntimeError("评估链未返回可用方案")
    msg, cost = chains.format_evaluation(evaluation)
    await send_text(cid, msg)

    _save_session(cid, scripts=review, evaluation=evaluation, style_name=style.name, current_theme=theme, source=vertical_key)


async def run_auto_video_job(
    chat_id: str,
    theme: str,
    style_name: str = "hot_news_commentary",
    choice_idx: int = 1,
    source: str = "auto",
) -> dict:
    """Worker-safe helper: generate a video end-to-end without manual confirm."""
    style = get_template(style_name)
    async with _sem:
        await send_text(chat_id, f"自动任务启动（{source}）：{theme}")
        await _run_vertical(chat_id, theme, style, style_name)
        await _handle_confirm(chat_id, f"确认 {choice_idx}")
    return {
        "theme": theme,
        "style_name": style_name,
        "choice_idx": choice_idx,
        "source": source,
        "last_video_id": (_get_session(chat_id) or {}).get("last_video_id", ""),
    }


async def _run_rewrite(cid: str, source: str, style: StyleTemplate) -> None:
    await send_text(cid, f"改写链启动（风格：{style.display_name}）...")
    scripts = await chains.lobster_rewrite(source, style)
    ok, reason = content_guard(scripts)
    if not ok:
        await send_text(cid, f"改写内容被拦截：{reason}")
        return

    evaluation = await chains.lobster_evaluate(scripts)
    if not evaluation.get("plans"):
        raise RuntimeError("评估链未返回可用方案")
    msg, cost = chains.format_evaluation(evaluation)
    await send_text(cid, msg)

    _save_session(cid, scripts=scripts, evaluation=evaluation, style_name=_current_style, current_theme=source, source="rewrite")


async def _handle_confirm(cid: str, text: str) -> None:
    session = _get_session(cid)
    if not session or "evaluation" not in session:
        await send_text(cid, "没有待确认的方案。请先发「解说 <话题>」或「任务 <主题>」生成解说稿。")
        return

    parts = text.strip().split()
    choice_idx = 1
    if len(parts) >= 2:
        try:
            choice_idx = int(parts[1])
        except ValueError:
            choice_idx = 1

    evaluation = session["evaluation"]
    plans = evaluation.get("plans", [])
    if not plans:
        await send_text(cid, "评估数据异常，没有可用方案。请重新发创作指令。")
        return

    if choice_idx < 1 or choice_idx > len(plans):
        await send_text(cid, f"方案序号 {choice_idx} 不存在，共 {len(plans)} 条。发「确认 1」到「确认 {len(plans)}」")
        return

    plan = plans[choice_idx - 1]
    style_name = session.get("style_name", _current_style)
    current_skill = session.get("current_skill", _current_skill)
    source_name = session.get("source", "manual")
    style = get_template(style_name)
    scripts_text = session.get("scripts", "")
    operator = plan.get("angle", plan.get("operator", "解说"))
    current_theme = session.get("current_theme", operator)
    gs_id: str | None = None
    try:
        gs_id = await _gs_create(
            chat_id=cid,
            skill_id=current_skill or None,
            theme=str(current_theme or ""),
        )
        _save_session(cid, generation_session_id=gs_id)
        log.info("[端到端] 创建 generation_session sid=%s", gs_id)
    except Exception as exc:
        log.warning("[端到端] generation_session 创建失败（不阻断）: %s", exc)

    # ════════════════════════════════════════���═
    # 步骤 0：角色 IP 解析
    # ══════════════════════════════════════════
    character = None
    character_ref_path = None
    if _current_character:
        character = get_character(_current_character)
    if not character:
        character = resolve_operator_to_character(operator, style_name)
    if character:
        ref = character.best_ref_path()
        if ref:
            character_ref_path = str(ref)
        log.info("[端到端] 角色IP: %s (参考图=%s)", character.display_name, bool(character_ref_path))
    if gs_id:
        try:
            if character:
                await _gs_lock_character(gs_id, character.key)
            await _gs_lock_storyboard(
                gs_id,
                storyboard_id=plan.get("plan_id") or f"plan_{int(time.time())}",
                plan_id=plan.get("plan_id"),
            )
            await _gs_update(gs_id, status="in_progress")
        except Exception as exc:
            log.warning("[端到端] P8 lock_character/storyboard 失败（不阻断）: %s", exc)

    char_info = f"，角色：{character.display_name}" if character else ""
    await send_text(cid, f"确认方案{choice_idx}（{operator}{char_info}，{plan.get('total_duration_sec', '?')}秒），开始生成...")

    # ══════════════════════════════════════════
    # 步骤 P5-a：Hook 增强（Phase 5）
    # ══════════════════════════════════════════
    narration_text = ""
    for clip in plan.get("clips", []):
        seg = clip.get("narration_segment", "")
        if seg:
            narration_text += seg + " "
    narration_text = narration_text.strip() or scripts_text[:400]

    hook_result = None
    try:
        from layers.L2_creative.hook_engine import generate_hook_variants, format_hook_variants
        hook_result = await generate_hook_variants(narration_text, style_name, n=3)
        hook_msg = format_hook_variants(hook_result)
        await send_text(cid, hook_msg)
    except Exception as e:
        log.warning("[端到端] Hook生成失败，跳过: %s", e)

    # ══════════════════════════════════════════
    # 步骤 P5-b：注意力曲线标注（Phase 5）
    # ══════════════════════════════════════════
    rhythm_plan = None
    rhythm_density = 0.0
    try:
        from layers.L2_creative.rhythm_engine import annotate_rhythm
        total_sec = float(plan.get("total_duration_sec", 25))
        rhythm_plan = await annotate_rhythm(narration_text, total_sec, style_name)
        rhythm_density = rhythm_plan.density_score
        log.info("[端到端] 节奏标注完成，密度=%.1f/10s", rhythm_density)
    except Exception as e:
        log.warning("[端到端] 节奏标注失败，跳过: %s", e)

    # ══════════════════════════════════════════
    # 步骤 1：生成视觉提示词（best-effort，失败用 fallback）
    # ══════════════════════════════════════════
    clips_spec = plan.get("clips", [])
    fallback_scene = clips_spec[0].get("scene_summary", operator) if clips_spec else operator

    vi = {}
    try:
        log.info("[端到端] 步骤1: lobster_visual (角色=%s)", character.display_name if character else "无")
        selected_script = f"方案{choice_idx}：{operator}，场景：{fallback_scene}"
        visual_raw = await chains.lobster_visual(selected_script, style, character=character)
        vi = parse_json_object(visual_raw)
        log.info("[端到端] lobster_visual 解析结果 keys=%s, captions=%s", list(vi.keys()), vi.get("captions"))
        if not vi.get("image_prompt"):
            items = parse_json_array(visual_raw)
            if items:
                vi = items[0]
    except Exception as e:
        log.warning("[端到端] lobster_visual 失败，使用 fallback: %s", e)

    # fallback：用评估数据的 scene_summary 构建提示词
    image_prompt = vi.get("image_prompt", "")
    kling_prompt = vi.get("kling_prompt", "")
    shot_map = _shot_map_from_visual(vi)
    template_shot_map = _shot_template_map(style.name)

    if not image_prompt:
        image_prompt = f"{fallback_scene}, {style.image_prompt_suffix}" if style.image_prompt_suffix else fallback_scene
        log.info("[端到端] image_prompt fallback: %s", image_prompt[:80])
    if not kling_prompt:
        kling_prompt = fallback_scene
        log.info("[端到端] kling_prompt fallback: %s", kling_prompt[:80])

    captions = vi.get("captions", [])
    if not captions:
        captions = [fallback_scene]
        log.info("[端到端] captions fallback: %s", captions)
    vi_tags = vi.get("tags", [])
    plan_duration_sec = float(plan.get("total_duration_sec", 0) or 0)
    # Burn-in subtitles must follow the spoken narration.  Visual captions from
    # lobster_visual are keywords for screen design and can drift from TTS text.
    timed_captions = _rebuild_timed_captions_from_narration(
        clips_spec,
        narration_text,
        plan_duration_sec,
    )

    # ══════════════════════════════════════════
    # 步骤 2：组装 clips + 生成视频
    # ══════════════════════════════════════════
    enriched_clips = []
    for clip in clips_spec:
        clip_no = int(clip["clip_no"])
        shot = shot_map.get(clip_no, {})
        clip_scene = clip.get("scene_summary", "")
        clip_image_prompt = shot.get("image_prompt") or clip.get("image_prompt") or image_prompt or clip_scene
        clip_kling_prompt = shot.get("kling_prompt") or clip.get("kling_prompt") or kling_prompt or clip_scene
        template_shot = template_shot_map.get(clip_no, {})
        clip_camera_control = _normalize_camera_control(
            shot.get("camera_control")
            or clip.get("camera_control")
            or template_shot.get("camera_control")
        )
        enriched_clips.append({
            "clip_no": clip_no,
            "duration_sec": clip.get("duration_sec", 5),
            "narration_segment": clip.get("narration_segment", ""),
            "scene_summary": clip_scene,
            "image_prompt": _safe_visual_prompt(clip_image_prompt, fallback=clip_scene),
            "kling_prompt": _safe_visual_prompt(clip_kling_prompt, fallback=clip_scene),
            "camera_control": clip_camera_control,
            "quality": plan.get("quality", "standard"),
            "status": "pending",
            "regen_count": 0,
            "locked_at": None,
            "dirty_reason": None,
            "last_hints": [],
        })

    if not enriched_clips:
        enriched_clips = [{
            "clip_no": 1, "duration_sec": 5,
            "narration_segment": narration_text,
            "scene_summary": fallback_scene,
            "image_prompt": _safe_visual_prompt(image_prompt, fallback=fallback_scene),
            "kling_prompt": _safe_visual_prompt(kling_prompt, fallback=fallback_scene),
            "camera_control": None,
            "quality": "standard",
            "status": "pending",
            "regen_count": 0,
            "locked_at": None,
            "dirty_reason": None,
            "last_hints": [],
        }]

    cfg = get_settings()
    if not cfg.use_legacy_av_pipeline:
        try:
            clip_plans: list[ClipPlan] = plan_clip_durations(enriched_clips)
            for idx, plan_item in enumerate(clip_plans):
                if idx < len(enriched_clips):
                    enriched_clips[idx]["duration_sec"] = plan_item.target_video_sec
                if idx < len(clips_spec):
                    clips_spec[idx]["duration_sec"] = plan_item.target_video_sec
            await send_text(cid, format_plan_for_feishu(clip_plans))
            log.info(
                "[端到端] P3 时长规划: %d clips, fallback=%d",
                len(clip_plans),
                sum(1 for p in clip_plans if p.is_fallback),
            )
        except Exception as e:
            log.warning("[端到端] P3 时长规划失败，走旧路径: %s", e)
    else:
        log.info("[端到端] use_legacy_av_pipeline=True，跳过 P3 时长规划")

    anchors = StoryAnchors()
    try:
        first_clip = enriched_clips[0] if enriched_clips else {}
        anchors = await extract_anchors_from_first_clip(
            clip_prompt=str(first_clip.get("image_prompt", "")),
            clip_narration=str(first_clip.get("narration_segment", "")),
            skill_name=str(current_skill or style_name or ""),
            storyboard_id=plan.get("plan_id"),
        )
        if anchors.characters or anchors.scenes:
            # D41-A.1: clip 1 is the anchor source, so inject only into later clips.
            for idx, clip in enumerate(enriched_clips):
                if idx == 0:
                    continue
                clip["image_prompt"] = inject_anchors_into_prompt(clip.get("image_prompt", ""), anchors)
                clip["kling_prompt"] = inject_anchors_into_prompt(clip.get("kling_prompt", ""), anchors)
            await _store_storyboard_anchors_guarded(plan.get("plan_id"), anchors)
            log.info(
                "[anchors] injected anchors into %d clips (skip clip 1 as source; characters=%d scenes=%d)",
                max(0, len(enriched_clips) - 1),
                len(anchors.characters),
                len(anchors.scenes),
            )
        else:
            log.info("[anchors] empty anchors; skip prompt injection")
    except Exception as exc:
        anchors = StoryAnchors()
        log.warning("[anchors] extraction/injection failed, continue without blocking: %s", exc)

    ts = int(time.time())
    output_dir = str(cfg.output_dir / f"job_{ts}")
    os.makedirs(output_dir, exist_ok=True)

    total_clips = len(enriched_clips)
    await send_text(cid, f"开始生成视频（{total_clips} 段，预计 3-10 分钟）...")

    voice_key = character.key if character else chains.get_voice_for_style(style_name)
    review_state = {
        "choice_idx": choice_idx,
        "generation_session_id": gs_id,
        "operator": operator,
        "style_name": style_name,
        "current_skill": current_skill,
        "source_name": source_name,
        "current_theme": current_theme,
        "scripts_text": scripts_text,
        "plan": plan,
        "narration_text": narration_text,
        "fallback_scene": fallback_scene,
        "captions": captions,
        "timed_captions": timed_captions,
        "plan_duration_sec": plan_duration_sec,
        "image_prompt": image_prompt,
        "vi_tags": vi_tags,
        "output_dir": output_dir,
        "enriched_clips": enriched_clips,
        "clip_paths": [],
        "total_clips": total_clips,
        "rhythm_plan": rhythm_plan,
        "rhythm_density": rhythm_density,
        "anchors": anchors.model_dump(mode="json"),
        "voice_key": voice_key,
        "character_ref_path": character_ref_path,
        "prev_tail_frame": None,
    }
    await _start_or_resume_visual_clip_review(cid, review_state, start_index=0)
    return

    clip_paths = []
    prev_tail_frame = None
    for i, clip in enumerate(enriched_clips):
        try:
            log.info(
                "[端到端] 生成片段 %d/%d (角色参考=%s, 链式首帧=%s)",
                i + 1,
                total_clips,
                bool(character_ref_path),
                bool(prev_tail_frame),
            )
            if clip.get("camera_control"):
                log.info(
                    "[端到端] 多角度镜头: clip_%02d camera=%s",
                    clip["clip_no"],
                    clip["camera_control"],
                )
            from layers.L3_visual.image_to_video import generate_clip, extract_last_frame
            out_path = os.path.join(output_dir, f"clip_{clip['clip_no']:02d}.mp4")
            video_result = await generate_clip(
                image_prompt=clip["image_prompt"],
                kling_prompt=clip["kling_prompt"],
                output_path=out_path,
                style=style,
                duration_sec=clip["duration_sec"],
                quality=clip["quality"],
                character_ref_path=character_ref_path,
                first_frame_path=prev_tail_frame,
                camera_control=clip.get("camera_control"),
                storyboard_id=plan.get("plan_id"),
                clip_no=clip.get("clip_no"),
            )
            if getattr(video_result, "clip_warning", ""):
                await send_text(cid, video_result.clip_warning)
            clip_paths.append(out_path)
            if i + 1 < total_clips:
                tail_out = os.path.join(output_dir, f"tail_{clip['clip_no']:02d}.png")
                try:
                    extract_last_frame(out_path, tail_out)
                    prev_tail_frame = tail_out
                    log.info("[端到端] 尾帧接力: clip_%02d → %s", clip["clip_no"], tail_out)
                except Exception as tail_error:
                    prev_tail_frame = None
                    log.warning("[端到端] 尾帧抽取失败，下段回退文生图: %s", tail_error)
        except Exception as e:
            prev_tail_frame = None
            await _record_fail_guarded(
                cid,
                stage="clip",
                exc=e,
                metadata={"clip_index": i + 1, "clip_no": clip.get("clip_no")},
            )
            log.error("[端到端] 片段%d 生成失败: %s", i + 1, e, exc_info=True)
            await send_text(cid, f"片段{i + 1} 生成失败：{str(e)[:100]}，跳过继续...")

    if not clip_paths:
        await send_text(cid, "所有片段生成失败，请检查可灵 API 余额和配置。")
        return

    # ══════════════════════════════════════════
    # 步骤 3：FFmpeg 拼接
    # ══════════════════════════════════════════
    final_path = os.path.join(output_dir, "final.mp4")
    if len(clip_paths) == 1:
        final_path = clip_paths[0]
    else:
        try:
            concat_clips(clip_paths, final_path)
        except Exception as e:
            log.error("[端到端] 拼接失败: %s", e)
            final_path = clip_paths[0]
            await send_text(cid, "拼接失败，先发第一段视频...")

    file_size_mb = os.path.getsize(final_path) / 1024 / 1024
    log.info("[端到端] 拼接完成: %s (%.1fMB)", final_path, file_size_mb)

    voice_key = character.key if character else chains.get_voice_for_style(style_name)
    _save_session(
        cid,
        pending_visual_review={
            "choice_idx": choice_idx,
            "operator": operator,
            "style_name": style_name,
            "source_name": source_name,
            "current_theme": current_theme,
            "scripts_text": scripts_text,
            "plan": plan,
            "narration_text": narration_text,
            "fallback_scene": fallback_scene,
            "captions": captions,
            "timed_captions": timed_captions,
            "plan_duration_sec": plan_duration_sec,
            "image_prompt": image_prompt,
            "vi_tags": vi_tags,
            "output_dir": output_dir,
            "final_path": final_path,
            "clip_paths": clip_paths,
            "total_clips": total_clips,
            "rhythm_plan": rhythm_plan,
            "rhythm_density": rhythm_density,
            "voice_key": voice_key,
        },
    )
    await send_file(
        cid,
        final_path,
        title=f"visual_preview_plan_{choice_idx}.mp4",
        caption="视觉片段已生成，请人工检查是否有伪文字/乱码。确认没问题后回复「确认」或「继续」，我再做配音、字幕、封面和最终成片。",
    )
    return

    # ══════════════════════════════════════════
    # 步骤 4：音频层（配音 + 音效 + BGM + 混音）
    # ══════════════════════════════════════════
    await send_text(cid, "视频片段就绪，开始音频处理...")

    voice_key = character.key if character else chains.get_voice_for_style(style_name)
    voiceover_path = None
    voiceover_result = None
    if narration_text:
        try:
            log.info("[端到端] 步骤4a: TTS 配音")
            voiceover_text = narration_text
            vo_out = os.path.join(output_dir, "voiceover.mp3")
            log.info("[端到端] TTS 选用音色: %s", voice_key)
            voiceover_result = await tts_synthesize(text=voiceover_text, output_path=vo_out, voice=voice_key)
            voiceover_path = vo_out
        except Exception as e:
            await _record_fail_guarded(cid, stage="final", exc=e, error_code="TTS_TIMEOUT")
            log.warning("[端到端] TTS 配音失败，继续无配音: %s", e)

    sfx_items = []
    try:
        log.info("[端到端] 步骤4b: 音效匹配")
        sfx_plan = await analyze_scene_sfx(fallback_scene, video_duration_sec=plan.get("total_duration_sec", 10))
        sfx_items = sfx_plan.items
    except Exception as e:
        log.warning("[端到端] 音效匹配失败: %s", e)

    bgm_path = None
    bgm_volume = 0.3
    try:
        log.info("[端到端] 步骤4c: BGM 匹配")
        script_text = f"{operator} {fallback_scene} {' '.join(captions)}"
        bgm_match = await analyze_mood(script_text)
        if bgm_match.file_path:
            bgm_path = str(bgm_match.file_path)
            bgm_volume = bgm_match.volume_ratio
            log.info("[端到端] BGM: %s (%s, vol=%.2f)", bgm_match.mood_name, bgm_path, bgm_volume)
    except Exception as e:
        log.warning("[端到端] BGM 匹配失败: %s", e)

    mixed_path = final_path
    if voiceover_path or bgm_path or sfx_items:
        try:
            log.info("[端到端] 步骤4d: 多轨混音")
            mixed_out = os.path.join(output_dir, "mixed.mp4")
            await mix_simple(
                video_path=final_path,
                output_path=mixed_out,
                voiceover_path=voiceover_path,
                bgm_path=bgm_path,
                bgm_volume=bgm_volume,
                sfx_items=sfx_items,
            )
            mixed_path = mixed_out
        except Exception as e:
            log.warning("[端到端] 混音失败，使用原始视频: %s", e)

    av_sync_report: AvSyncReport | None = None
    if mixed_path != final_path and voiceover_path:
        corrected_out = os.path.join(output_dir, "mixed_corrected.mp4")
        try:
            av_sync_report = check_and_correct_av_sync(
                video_path=final_path,
                voiceover_path=voiceover_path,
                mixed_path=mixed_path,
                corrected_output_path=corrected_out,
            )
            if av_sync_report.correction_applied not in ("none", "no_voiceover"):
                mixed_path = corrected_out
            await send_text(cid, "音画同步：" + av_sync_report.to_feishu_line())
        except AVDriftTooLargeError as drift_err:
            rescued_path = await _attempt_av_rescue_guarded(
                cid,
                mixed_path=mixed_path,
                video_path=final_path,
                voiceover_path=voiceover_path,
                narration_text=narration_text,
                drift_err=drift_err,
                output_dir=output_dir,
                voice_key=voice_key,
                storyboard_id=plan.get("plan_id"),
            )
            if rescued_path:
                mixed_path = rescued_path
            else:
                await _record_fail_guarded(
                    cid,
                    stage="final",
                    exc=drift_err,
                    error_code="AV_DRIFT",
                    metadata=drift_err.report.model_dump(),
                )
                log.error("[端到端] 音画漂移过大，救援失败，不发成片: %s", drift_err)
                await send_text(cid, "音画同步：" + drift_err.report.to_feishu_line())
                await send_text(
                    cid,
                    f"🔴 音画漂移过大且救援失败，不发成片\n{drift_err.report.to_feishu_line()}\n"
                    f"建议：缩短旁白、拆段，或重新生成本条视频"
                )
                return
        except Exception as av_err:
            log.warning("[端到端] av_sync 检查失败但不阻断: %s", av_err)

    # ══════════════════════════════════════════
    # 步骤 5：后期包装（字幕 + 封面 + 压缩）
    # ══════════════════════════════════════════
    await send_text(cid, "音频处理完成，开始后期包装...")

    captioned_path = mixed_path
    if _caption_burn_enabled() and (timed_captions or narration_text):
        try:
            log.info("[端到端] 步骤5a: 烧录字幕")
            cap_out = os.path.join(output_dir, "captioned.mp4")
            caption_style = style.caption_style if hasattr(style, 'caption_style') and style.caption_style in (
                "military", "cute", "drama", "danmaku", "minimal", "cinematic"
            ) else "military"
            voiceover_duration_sec = (
                getattr(voiceover_result, "duration_ms", 0) / 1000.0
                if voiceover_result else 0.0
            )
            caption_duration_sec = voiceover_duration_sec or plan_duration_sec
            timed_captions = _rebuild_timed_captions_from_narration(
                clips_spec,
                narration_text,
                caption_duration_sec,
            )
            log.info(
                "[端到端] 字幕统一基于 narration 重建: %d items（plan-based=%s）",
                len(timed_captions),
                bool(_build_timed_captions_from_plan(clips_spec)),
            )
            if not timed_captions:
                log.warning("[端到端] 无可用字幕文本，跳过字幕烧录")
            else:
                await burn_captions(
                    video_path=mixed_path,
                    output_path=cap_out,
                    captions=timed_captions,
                    style=caption_style,
                )
                captioned_path = cap_out
        except Exception as e:
            log.warning("[端到端] 字幕烧录失败: %s", e)

    elif timed_captions or narration_text:
        log.info("[end_to_end] caption burn disabled; keeping mixed video without burned subtitles")

    cover_path = None
    try:
        log.info("[端到端] 步骤5b: 生成封面")
        cover_out = os.path.join(output_dir, "cover.jpg")
        op_title = f"{operator}的故事"
        await generate_cover(
            video_path=captioned_path,
            output_path=cover_out,
            title=op_title,
            frame_sec=1.0,
        )
        cover_path = cover_out
    except Exception as e:
        log.warning("[端到端] 封面生成失败: %s", e)

    compressed_path = captioned_path
    try:
        log.info("[端到端] 步骤5c: 压缩（douyin 预设）")
        comp_out = os.path.join(output_dir, "final_compressed.mp4")
        await compress(input_path=captioned_path, output_path=comp_out, preset="douyin")
        compressed_path = comp_out
    except Exception as e:
        log.warning("[端到端] 压缩失败，使用未压缩版本: %s", e)

    final_output = compressed_path
    file_size_mb = os.path.getsize(final_output) / 1024 / 1024
    log.info("[端到端] 完成: %s (%.1fMB)", final_output, file_size_mb)

    # ══════════════════════════════════════════
    # 步骤 P5-c：节奏化剪辑（Phase 5）
    # ══════════════════════════════════════════
    rhythm_edit_result = None
    if rhythm_plan:
        try:
            from layers.L5_postprod.rhythm_editor import apply_rhythm
            rhythm_out = os.path.join(output_dir, "rhythmed.mp4")
            rhythm_edit_result = await apply_rhythm(final_output, rhythm_out, rhythm_plan)
            if rhythm_edit_result.output_path != final_output and os.path.exists(rhythm_edit_result.output_path):
                final_output = rhythm_edit_result.output_path
                file_size_mb = os.path.getsize(final_output) / 1024 / 1024
            log.info("[端到端] 节奏剪辑完成：sfx=%d cues", len(rhythm_edit_result.sfx_cues))
        except Exception as e:
            log.warning("[端到端] 节奏剪辑失败，跳过: %s", e)

    # ══════════════════════════════════════════
    # 步骤 P5-d：质量关卡（Phase 5）
    # ══════════════════════════════════════════
    quality_passed = True
    try:
        from layers.L7_optimization.quality_gate import score_content, format_quality_report, PASS_THRESHOLD
        q_score = await score_content(
            narration=narration_text,
            image_prompt=image_prompt,
            style_name=style_name,
            rhythm_density=rhythm_density,
            voice_key=voice_key,
        )
        quality_report = format_quality_report(q_score)
        await send_text(cid, quality_report)
        quality_passed = q_score.passed
        if not quality_passed:
            await send_text(cid, f"⚠️ 质量评分 {q_score.total:.0f}/100，低于{PASS_THRESHOLD}分。\n视频仍已生成，建议参考改进建议后重新生成。")
    except Exception as e:
        log.warning("[端到端] 质量关卡评分失败，跳过: %s", e)

    # ══════════════════════════════════════════
    # Sprint 3：VL 成片质检（真实看关键帧）
    # ══════════════════════════════════════════
    vl_score = None
    try:
        from layers.L7_optimization.critic_engine import (
            format_vl_critic_report,
            score_video_with_vl,
        )
        caption_sample = "\n".join(
            item.text if hasattr(item, "text") else str(item)
            for item in (timed_captions[:3] if "timed_captions" in locals() else [])
        )
        vl_score = await asyncio.to_thread(
            score_video_with_vl,
            final_output,
            narration=narration_text,
            style_name=style_name,
            caption_sample=caption_sample,
            frame_count=6,
            regen_attempt=0,
        )
        await send_text(cid, format_vl_critic_report(vl_score))
        if vl_score.should_regenerate:
            await send_text(
                cid,
                "成片质检建议重生。当前先回传成片供人工查看；下一步可基于报告重新生成一次，避免无限烧 API。",
            )
    except Exception as e:
        log.warning("[端到端] VL 成片质检失败，跳过: %s", e)

    # ══════════════════════════════════════════
    # 步骤 6：运营文案（best-effort）+ 飞书回传
    # ══════════════════════════════════════════
    op = {}
    try:
        op_raw = chains.lobster_operation(scripts_text)
        op_items = parse_json_array(op_raw)
        if op_items:
            op = op_items[min(choice_idx - 1, len(op_items) - 1)]
    except Exception as e:
        log.warning("[端到端] lobster_operation 失败: %s", e)

    await send_file(cid, final_output, title=f"方案{choice_idx}.mp4")

    if cover_path and os.path.exists(cover_path):
        await send_file(cid, cover_path, title=f"封面_{choice_idx}.jpg")

    title = op.get("title", "")
    tags = op.get("tags", vi_tags)
    video_id = ""
    try:
        q_total = (
            vl_score.total
            if vl_score is not None and getattr(vl_score, "valid", True)
            else (q_score.total if 'q_score' in locals() else None)
        )
        video_id = await _record_video_output(
            chat_id=cid,
            source=source_name,
            style_name=style_name,
            theme=current_theme or operator,
            title=title,
            narration=narration_text,
            tags=tags if isinstance(tags, list) else [],
            video_path=final_output,
            cover_path=cover_path,
            quality_score=q_total,
            plan_id=None,
        )
    except Exception as e:
        log.warning("[端到端] 视频记录入库失败: %s", e)

    if title:
        await send_text(cid, f"【标题】{title}")
    if tags:
        tag_str = " ".join(f"#{t}" for t in tags) if isinstance(tags, list) else str(tags)
        await send_text(cid, f"【话题】{tag_str}")
    if captions:
        cap_text = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(captions))
        await send_text(cid, f"【字幕】\n{cap_text}")

    # ── Phase 5：首评话术推送 ──
    try:
        from layers.L2_creative.comment_engine import generate_comments, format_comment_plan
        comment_plan = await generate_comments(
            narration=narration_text,
            style_name=style_name,
            title=title,
        )
        await send_text(cid, format_comment_plan(comment_plan))
    except Exception as e:
        log.warning("[端到端] 首评话术生成失败: %s", e)

    summary_parts = [
        f"视频生成完成（{file_size_mb:.1f}MB，{len(clip_paths)}/{total_clips} 段成功）",
    ]
    if video_id:
        summary_parts.append(f"视频ID：{video_id}")
    if voiceover_path:
        summary_parts.append("已添加 AI 配音")
    if bgm_path:
        summary_parts.append(f"BGM: {bgm_match.mood_name}")
    if cover_path:
        summary_parts.append("已生成封面")
    if rhythm_plan:
        summary_parts.append(f"节奏标注 {len(rhythm_plan.attention_points)} 个刺激点")

    await send_text(cid, "。".join(summary_parts) + "。")

    _save_session(
        cid,
        last_video_path=final_output,
        last_title=title,
        last_tags=tags if isinstance(tags, list) else [],
        last_cover_path=cover_path,
        last_plan_id="",
        last_video_id=video_id,
    )
    await _notify_video_ready(cid)
    try:
        gs_id = (_get_session(cid) or {}).get("generation_session_id")
        if gs_id:
            await _gs_update(gs_id, status="completed")
            await _gs_emit(gs_id, stage="final", decision="completed")
            await _send_final_score_prompt(cid, gs_id)
    except Exception as exc:
        log.warning("[端到端] P8 mark session completed 失败（不阻断）: %s", exc)


# ══════════════════════════════════════════
# Sprint 2：VLM 改编链（B 站 URL / 本地路径 / 飞书文件）
# ══════════════════════════════════════════

def _parse_visual_review_command(text: str) -> tuple[str, str]:
    raw = str(text or "").strip()
    if raw in {"1", "1.", "1.继续", "继续", "确认", "确认片段"}:
        return "continue", ""
    if raw.startswith("2") or raw.startswith("重新生成"):
        for sep in (":", "："):
            if sep in raw:
                return "regenerate", raw.split(sep, 1)[1].strip()
        return "regenerate", ""
    if raw.startswith("3") or raw.startswith("取消"):
        for sep in (":", "："):
            if sep in raw:
                return "cancel", raw.split(sep, 1)[1].strip()
        return "cancel", ""
    return "", ""


def _remember_visual_review_action(style_name: str, action: str, note: str) -> None:
    try:
        from core.dreaming_scheduler import MemoryProposal, append_approved_memory
        prompt_rule = {
            "continue": "用户人工审核通过当前视觉片段，类似画面表达可继续沿用。",
            "regenerate": f"用户要求重生成视觉片段，修改意见：{note or '未填写具体意见'}。后续生成要优先遵守这类人工改动偏好。",
            "cancel": f"用户取消了当前视频生成，原因或上下文：{note or '未填写具体原因'}。后续类似方向应谨慎生成。",
        }.get(action, note)
        append_approved_memory(
            MemoryProposal(
                id=uuid.uuid4().hex[:8].upper(),
                style_name=style_name or "global",
                insight="人工片段审核反馈",
                evidence=note or action,
                prompt_rule=prompt_rule,
                confidence=0.85,
            )
        )
    except Exception as exc:
        log.warning("[visual_review] memory write skipped: %s", exc)


async def _finalize_after_visual_clips(cid: str, review: dict) -> None:
    choice_idx = int(review.get("choice_idx", 1))
    operator = review.get("operator", "解说")
    style_name = review.get("style_name", _current_style)
    source_name = review.get("source_name", "manual")
    current_theme = review.get("current_theme", operator)
    scripts_text = review.get("scripts_text", "")
    plan = review.get("plan", {})
    narration_text = review.get("narration_text", "")
    fallback_scene = review.get("fallback_scene", operator)
    captions = review.get("captions", [])
    timed_captions = review.get("timed_captions", [])
    plan_duration_sec = float(review.get("plan_duration_sec", 0) or 0)
    clips_spec = plan.get("clips", []) if isinstance(plan, dict) else []
    image_prompt = review.get("image_prompt", "")
    vi_tags = review.get("vi_tags", [])
    output_dir = review.get("output_dir", "")
    clip_paths = review.get("clip_paths", [])
    total_clips = int(review.get("total_clips", len(clip_paths) or 1))
    rhythm_plan = review.get("rhythm_plan")
    rhythm_density = float(review.get("rhythm_density", 0.0) or 0.0)
    voice_key = review.get("voice_key") or chains.get_voice_for_style(style_name)
    style = get_template(style_name)

    final_path = os.path.join(output_dir, "final.mp4")
    if len(clip_paths) == 1:
        final_path = clip_paths[0]
    else:
        try:
            concat_clips(clip_paths, final_path)
        except Exception as exc:
            log.error("[visual_review] concat failed: %s", exc)
            final_path = clip_paths[0]
            await send_text(cid, "拼接失败，先用第一段继续后期。")

    await send_text(cid, "视觉片段已全部确认，开始配音、字幕和最终成片...")

    voiceover_path = None
    voiceover_result = None
    if narration_text:
        try:
            vo_out = os.path.join(output_dir, "voiceover.mp3")
            voiceover_result = await tts_synthesize(text=narration_text, output_path=vo_out, voice=voice_key)
            voiceover_path = vo_out
        except Exception as exc:
            await _record_fail_guarded(cid, stage="final", exc=exc, error_code="TTS_TIMEOUT")
            log.warning("[visual_review] TTS failed: %s", exc)

    sfx_items = []
    try:
        sfx_plan = await analyze_scene_sfx(fallback_scene, video_duration_sec=plan.get("total_duration_sec", 10))
        sfx_items = sfx_plan.items
    except Exception as exc:
        log.warning("[visual_review] sfx failed: %s", exc)

    bgm_path = None
    bgm_volume = 0.3
    bgm_name = ""
    try:
        bgm_match = await analyze_mood(f"{operator} {fallback_scene} {' '.join(captions)}")
        bgm_name = getattr(bgm_match, "mood_name", "")
        if bgm_match.file_path:
            bgm_path = str(bgm_match.file_path)
            bgm_volume = bgm_match.volume_ratio
    except Exception as exc:
        log.warning("[visual_review] bgm failed: %s", exc)

    mixed_path = final_path
    if voiceover_path or bgm_path or sfx_items:
        try:
            mixed_out = os.path.join(output_dir, "mixed.mp4")
            await mix_simple(
                video_path=final_path,
                output_path=mixed_out,
                voiceover_path=voiceover_path,
                bgm_path=bgm_path,
                bgm_volume=bgm_volume,
                sfx_items=sfx_items,
            )
            mixed_path = mixed_out
        except Exception as exc:
            log.warning("[visual_review] mix failed: %s", exc)

    av_sync_report: AvSyncReport | None = None
    if mixed_path != final_path and voiceover_path:
        corrected_out = os.path.join(output_dir, "mixed_corrected.mp4")
        try:
            av_sync_report = check_and_correct_av_sync(
                video_path=final_path,
                voiceover_path=voiceover_path,
                mixed_path=mixed_path,
                corrected_output_path=corrected_out,
            )
            if av_sync_report.correction_applied not in ("none", "no_voiceover"):
                mixed_path = corrected_out
            await send_text(cid, "音画同步：" + av_sync_report.to_feishu_line())
        except AVDriftTooLargeError as drift_err:
            rescued_path = await _attempt_av_rescue_guarded(
                cid,
                mixed_path=mixed_path,
                video_path=final_path,
                voiceover_path=voiceover_path,
                narration_text=narration_text,
                drift_err=drift_err,
                output_dir=output_dir,
                voice_key=voice_key,
                storyboard_id=(review.get("plan") or {}).get("plan_id") or review.get("generation_session_id"),
            )
            if rescued_path:
                mixed_path = rescued_path
            else:
                await _record_fail_guarded(
                    cid,
                    stage="final",
                    exc=drift_err,
                    error_code="AV_DRIFT",
                    metadata=drift_err.report.model_dump(),
                )
                log.error("[端到端] 音画漂移过大，救援失败，不发成片: %s", drift_err)
                await send_text(cid, "音画同步：" + drift_err.report.to_feishu_line())
                await send_text(
                    cid,
                    f"🔴 音画漂移过大且救援失败，不发成片\n{drift_err.report.to_feishu_line()}\n"
                    f"建议：缩短旁白、拆段，或重新生成本条视频"
                )
                return
        except Exception as av_err:
            log.warning("[端到端] av_sync 检查失败但不阻断: %s", av_err)

    captioned_path = mixed_path
    if _caption_burn_enabled():
        try:
            cap_out = os.path.join(output_dir, "captioned.mp4")
            if timed_captions or narration_text:
                voiceover_duration_sec = (
                    getattr(voiceover_result, "duration_ms", 0) / 1000.0
                    if voiceover_result else 0.0
                )
                caption_duration_sec = voiceover_duration_sec or plan_duration_sec
                timed_captions = _rebuild_timed_captions_from_narration(
                    clips_spec,
                    narration_text,
                    caption_duration_sec,
                )
                log.info(
                    "[端到端] 字幕统一基于 narration 重建: %d items（plan-based=%s）",
                    len(timed_captions),
                    bool(_build_timed_captions_from_plan(clips_spec)),
                )
                if timed_captions:
                    await burn_captions(
                        video_path=mixed_path,
                        output_path=cap_out,
                        captions=timed_captions,
                        style=getattr(style, "caption_style", "military") or "military",
                    )
                else:
                    log.warning("[端到端] 无可用字幕文本，跳过字幕烧录")
            captioned_path = cap_out if os.path.exists(cap_out) else mixed_path
        except Exception as exc:
            log.warning("[visual_review] caption failed: %s", exc)
    else:
        log.info("[visual_review] caption burn disabled; keeping mixed video without burned subtitles")

    cover_path = None
    try:
        cover_out = os.path.join(output_dir, "cover.jpg")
        await generate_cover(captioned_path, cover_out, title=f"{operator}的故事", frame_sec=1.0)
        cover_path = cover_out
    except Exception as exc:
        log.warning("[visual_review] cover failed: %s", exc)

    final_output = captioned_path
    try:
        comp_out = os.path.join(output_dir, "final_compressed.mp4")
        await compress(input_path=captioned_path, output_path=comp_out, preset="douyin")
        final_output = comp_out
    except Exception as exc:
        log.warning("[visual_review] compress failed: %s", exc)

    if rhythm_plan:
        try:
            from layers.L5_postprod.rhythm_editor import apply_rhythm
            rhythm_out = os.path.join(output_dir, "rhythmed.mp4")
            rhythm_edit_result = await apply_rhythm(final_output, rhythm_out, rhythm_plan)
            if rhythm_edit_result.output_path != final_output and os.path.exists(rhythm_edit_result.output_path):
                final_output = rhythm_edit_result.output_path
        except Exception as exc:
            log.warning("[visual_review] rhythm failed: %s", exc)

    file_size_mb = os.path.getsize(final_output) / 1024 / 1024
    q_score = None
    try:
        from layers.L7_optimization.quality_gate import score_content, format_quality_report
        q_score = await score_content(
            narration=narration_text,
            image_prompt=image_prompt,
            style_name=style_name,
            rhythm_density=rhythm_density,
            voice_key=voice_key,
        )
        await send_text(cid, format_quality_report(q_score))
    except Exception as exc:
        log.warning("[visual_review] quality failed: %s", exc)

    vl_score = None
    try:
        from layers.L7_optimization.critic_engine import format_vl_critic_report, score_video_with_vl
        caption_sample = "\n".join(item.text if hasattr(item, "text") else str(item) for item in timed_captions[:3])
        vl_score = await asyncio.to_thread(
            score_video_with_vl,
            final_output,
            narration=narration_text,
            style_name=style_name,
            caption_sample=caption_sample,
            frame_count=6,
            regen_attempt=0,
        )
        await send_text(cid, format_vl_critic_report(vl_score))
    except Exception as exc:
        log.warning("[visual_review] vl score failed: %s", exc)

    op = {}
    try:
        op_items = parse_json_array(chains.lobster_operation(scripts_text))
        if op_items:
            op = op_items[min(choice_idx - 1, len(op_items) - 1)]
    except Exception as exc:
        log.warning("[visual_review] operation copy failed: %s", exc)

    await send_file(cid, final_output, title=f"方案{choice_idx}.mp4")
    if cover_path and os.path.exists(cover_path):
        await send_file(cid, cover_path, title=f"封面_{choice_idx}.jpg")

    title = op.get("title", "")
    tags = op.get("tags", vi_tags)
    video_id = ""
    try:
        q_total = (
            vl_score.total
            if vl_score is not None and getattr(vl_score, "valid", True)
            else (q_score.total if q_score is not None else None)
        )
        video_id = await _record_video_output(
            chat_id=cid,
            source=source_name,
            style_name=style_name,
            theme=current_theme or operator,
            title=title,
            narration=narration_text,
            tags=tags if isinstance(tags, list) else [],
            video_path=final_output,
            cover_path=cover_path,
            quality_score=q_total,
            plan_id=None,
        )
    except Exception as exc:
        log.warning("[visual_review] record failed: %s", exc)

    if title:
        await send_text(cid, f"【标题】{title}")
    if tags:
        tag_str = " ".join(f"#{t}" for t in tags) if isinstance(tags, list) else str(tags)
        await send_text(cid, f"【话题】{tag_str}")

    summary_parts = [f"视频生成完成（{file_size_mb:.1f}MB，{len(clip_paths)}/{total_clips} 段成功）"]
    if video_id:
        summary_parts.append(f"视频ID：{video_id}")
    if voiceover_path:
        summary_parts.append("已添加 AI 配音")
    if bgm_path:
        summary_parts.append(f"BGM: {bgm_name}")
    if cover_path:
        summary_parts.append("已生成封面")
    await send_text(cid, "。".join(summary_parts) + "。")

    session = _get_session(cid) or {}
    session.pop("pending_visual_clip_review", None)
    session.pop("pending_visual_review", None)
    _save_session(
        cid,
        last_video_path=final_output,
        last_title=title,
        last_tags=tags if isinstance(tags, list) else [],
        last_cover_path=cover_path,
        last_plan_id="",
        last_video_id=video_id,
    )
    await _notify_video_ready(cid)
    try:
        gs_id = (_get_session(cid) or {}).get("generation_session_id") or review.get("generation_session_id")
        if gs_id:
            await _gs_update(gs_id, status="completed")
            await _gs_emit(gs_id, stage="final", decision="completed")
            await _send_final_score_prompt(cid, gs_id)
    except Exception as exc:
        log.warning("[端到端] P8 mark session completed 失败（不阻断）: %s", exc)


async def _start_or_resume_visual_clip_review(cid: str, review: dict, *, start_index: int) -> None:
    style_name = review.get("style_name", _current_style)
    style = get_template(style_name)
    output_dir = review["output_dir"]
    enriched_clips = review["enriched_clips"]
    clip_paths = review.get("clip_paths", [])
    prev_tail_frame = review.get("prev_tail_frame")
    character_ref_path = review.get("character_ref_path")
    total_clips = int(review.get("total_clips", len(enriched_clips)))

    for idx in range(start_index, total_clips):
        clip = enriched_clips[idx]
        from layers.L3_visual.image_to_video import generate_clip
        out_path = os.path.join(output_dir, f"clip_{clip['clip_no']:02d}.mp4")
        video_result = await generate_clip(
            image_prompt=clip["image_prompt"],
            kling_prompt=clip["kling_prompt"],
            output_path=out_path,
            style=style,
            duration_sec=clip["duration_sec"],
            quality=clip["quality"],
            character_ref_path=character_ref_path,
            first_frame_path=prev_tail_frame,
            camera_control=clip.get("camera_control"),
            storyboard_id=(review.get("plan") or {}).get("plan_id") or review.get("generation_session_id"),
            clip_no=clip.get("clip_no"),
        )
        if getattr(video_result, "clip_warning", ""):
            await send_text(cid, video_result.clip_warning)
        if out_path not in clip_paths:
            clip_paths.append(out_path)
        review.update(
            current_index=idx,
            current_clip=clip,
            current_clip_path=out_path,
            clip_paths=clip_paths,
            prev_tail_frame=prev_tail_frame,
        )
        _save_session(cid, pending_visual_clip_review=review)
        clip_narration = (clip.get("narration_segment") or "").strip()
        narration_chars = len(clip_narration)
        est_audio_sec = estimate_narration_audio_sec(clip_narration)
        clip_cost = estimate_clip_cost(
            model="kling-v2-5-turbo",
            duration_sec=clip["duration_sec"],
            quality=clip.get("quality", "standard"),
            narration_char_count=narration_chars,
        )
        locked_count = sum(1 for c in enriched_clips if c.get("status") == "locked")
        pending_count = total_clips - locked_count
        cumulative_cost = estimate_clips_total_cost(
            enriched_clips[: idx + 1],
            model="kling-v2-5-turbo",
            quality=clip.get("quality", "standard"),
        )
        caption = (
            f"片段 {idx + 1}/{total_clips} 已生成（🔒 锁定 {locked_count} / ⏳ 待审 {pending_count}）\n"
            f"━━━━━━━━━━━━━━\n"
            f"📝 旁白（{narration_chars} 字）：{clip_narration[:80]}{'...' if narration_chars > 80 else ''}\n"
            f"⏱️ 视频 {clip['duration_sec']}s / 估 TTS {est_audio_sec:.2f}s\n"
            f"💰 本段 ¥{clip_cost:.2f} / 累计 ¥{cumulative_cost:.2f}\n"
            f"━━━━━━━━━━━━━━\n"
            f"回复：1.继续\n"
            f"或：2.重新生成: 你的改动意见（如 '人物近 + 不要文字'）\n"
            f"或：3.取消"
        )
        await send_file(
            cid,
            out_path,
            title=f"clip_{clip['clip_no']:02d}_preview.mp4",
            caption=caption,
        )
        return


async def _handle_visual_clip_review(cid: str, text: str) -> bool:
    session = _get_session(cid)
    if not session or not session.get("pending_visual_clip_review"):
        return False
    review_cmd: ReviewCommand = parse_review_command(text)
    if not review_cmd.is_actionable:
        return False
    action = review_cmd.action
    note = review_cmd.raw_note

    review = session["pending_visual_clip_review"]
    style_name = review.get("style_name", _current_style)
    current_index = int(review.get("current_index", 0))
    enriched_clips = review["enriched_clips"]
    current_clip = enriched_clips[current_index]
    current_path = review.get("current_clip_path")
    gs_id = session.get("generation_session_id") or review.get("generation_session_id")
    if gs_id:
        try:
            await _gs_emit(
                gs_id,
                stage="clip",
                decision="regen" if action == "regenerate" else action,
                clip_index=current_index + 1,
                comment=note,
                hints=review_cmd.hints,
                event_metadata={
                    "regen_count": current_clip.get("regen_count", 0),
                    "duration_sec": current_clip.get("duration_sec", 5),
                },
            )
        except Exception as exc:
            log.warning("[端到端] P8 emit clip event 失败（不阻断）: %s", exc)

    if action == "cancel":
        current_clip["status"] = "cancelled"
        _remember_visual_review_action(style_name, "cancel", note)
        try:
            if gs_id:
                await _gs_update(gs_id, status="cancelled")
        except Exception as exc:
            log.warning("[端到端] P8 mark session cancelled 失败（不阻断）: %s", exc)
        session.pop("pending_visual_clip_review", None)
        session.pop("pending_visual_review", None)
        await send_text(cid, "已取消这条视频的后续生成，并记录你的操作偏好。")
        return True

    if action == "regenerate":
        _remember_visual_review_action(style_name, "regenerate", note)
        if not note:
            await send_text(cid, "请用「2.重新生成: 你的改动意见」告诉我怎么改。")
            return True
        current_clip["status"] = "dirty"
        current_clip["dirty_reason"] = note
        current_clip["regen_count"] = current_clip.get("regen_count", 0) + 1
        current_clip["last_hints"] = review_cmd.hints
        current_clip["image_prompt"] = f"{current_clip.get('image_prompt', '')}, user revision: {note}"
        current_clip["kling_prompt"] = f"{current_clip.get('kling_prompt', '')}, user revision: {note}"
        review["clip_paths"] = [p for p in review.get("clip_paths", []) if p != current_path]
        await _start_or_resume_visual_clip_review(cid, review, start_index=current_index)
        return True

    from datetime import datetime
    current_clip["status"] = "locked"
    current_clip["locked_at"] = datetime.now().isoformat(timespec="seconds")
    _remember_visual_review_action(style_name, "continue", f"clip_index={current_index + 1}")
    total_clips = int(review.get("total_clips", len(enriched_clips)))
    if current_index + 1 >= total_clips:
        try:
            await _finalize_after_visual_clips(cid, review)
        except Exception as exc:
            try:
                gs_id = (_get_session(cid) or {}).get("generation_session_id") or review.get("generation_session_id")
                if gs_id:
                    await _gs_update(gs_id, status="failed")
                    await _gs_emit(gs_id, stage="final", decision="failed", comment=str(exc)[:500])
                    await _record_fail_guarded(
                        cid,
                        stage="final",
                        exc=exc,
                        session_id=gs_id,
                    )
            except Exception:
                pass
            raise
        return True

    try:
        from layers.L3_visual.image_to_video import extract_last_frame
        tail_out = os.path.join(review["output_dir"], f"tail_{current_clip['clip_no']:02d}.png")
        if current_path:
            extract_last_frame(current_path, tail_out)
            review["prev_tail_frame"] = tail_out
    except Exception as exc:
        review["prev_tail_frame"] = None
        log.warning("[visual_review] tail frame extraction failed: %s", exc)

    await _start_or_resume_visual_clip_review(cid, review, start_index=current_index + 1)
    return True


async def _download_video_url(url: str, dest_dir: str) -> str:
    """用 yt-dlp 下载视频到 dest_dir，返回本地路径。"""
    import subprocess, shutil, sys
    out_tmpl = os.path.join(dest_dir, "source.%(ext)s")
    dl_args = ["-o", out_tmpl, "--no-playlist", "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4/best"]
    # 如果配置了 cookies 文件（B站登录态），加入参数
    cookies_file = get_settings().ytdlp_cookies_file
    if cookies_file and os.path.isfile(cookies_file):
        dl_args += ["--cookies", cookies_file]
        log.info("[改编] 使用 cookies 文件: %s", cookies_file)
    dl_args.append(url)
    exe = shutil.which("yt-dlp")
    cmd = ([exe] + dl_args) if exe else ([sys.executable, "-m", "yt_dlp"] + dl_args)
    log.info("[改编] yt-dlp 下载: %s", url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        err = result.stderr
        if "412" in err or "Precondition Failed" in err:
            raise RuntimeError(
                "B站下载需要登录态（HTTP 412）。\n"
                "请直接把视频上传到飞书聊天，bot 会自动识别并改编。\n"
                "或在服务器配置 YTDLP_COOKIES_FILE 路径。"
            )
        raise RuntimeError(f"yt-dlp 下载失败: {err[-300:]}")
    for fname in os.listdir(dest_dir):
        if fname.startswith("source."):
            return os.path.join(dest_dir, fname)
    raise RuntimeError("yt-dlp 下载成功但找不到输出文件")


async def _run_rewrite_vlm(cid: str, source: str, style: StyleTemplate) -> None:
    """改编指令处理：支持 B站/任意 URL 或本地路径。"""
    is_url = source.startswith("http://") or source.startswith("https://")
    tmp_dir = None
    video_path = None

    try:
        if is_url:
            await send_text(cid, f"正在下载视频（yt-dlp）...\n{source[:80]}")
            tmp_dir = tempfile.mkdtemp(prefix="rewrite_vlm_")
            video_path = await _download_video_url(source, tmp_dir)
            await send_text(cid, f"下载完成，开始多帧分析（6 帧）...")
        elif os.path.isfile(source):
            video_path = source
            await send_text(cid, f"本地视频：{os.path.basename(source)}，开始多帧分析...")
        else:
            # 纯文字内容，降级为普通改编
            await send_text(cid, "未识别为视频路径/链接，以文字内容改编...")
            scripts = await chains.lobster_rewrite(source, style)
            ok, reason = content_guard(scripts)
            if not ok:
                await send_text(cid, f"内容被拦截：{reason}")
                return
            evaluation = await chains.lobster_evaluate(scripts)
            if not evaluation.get("plans"):
                raise RuntimeError("评估链未返回可用方案")
            msg, _ = chains.format_evaluation(evaluation)
            await send_text(cid, msg)
            _save_session(cid, scripts=scripts, evaluation=evaluation,
                          style_name=_current_style, current_theme=source, source="rewrite_text")
            return

        # VLM 改编路径：视觉 + 音频并行分析，再改写，结果存进 session
        await send_text(cid, "正在用 GLM-4V 分析视频画面（6 帧） + librosa/Whisper 分析 BGM...")
        understanding, audio = await asyncio.gather(
            chains.analyze_video_with_vlm(video_path, num_frames=6),
            analyze_audio(video_path),
            return_exceptions=False,
        )
        audio_summary = (
            f"  BGM：{audio.bpm} BPM（{audio.tempo_label}）"
            f"{'，有人声' if audio.has_vocals else '，纯BGM'}"
            if audio.has_audio else "  BGM：无音轨"
        )
        await send_text(
            cid,
            f"视频理解完成：\n"
            f"  类型：{understanding.video_type}/{understanding.sub_type or '-'}（能量{understanding.energy_level or '-'}）\n"
            f"  人物：{understanding.character_appearance[:60]}\n"
            f"  行为：{understanding.core_action[:60]}\n"
            f"  场景：{understanding.setting[:60]}\n"
            f"{audio_summary}\n"
            f"开始改写...",
        )

        char_name = ""
        if _current_character:
            _c = get_character(_current_character)
            char_name = _c.display_name if _c else _current_character

        scripts = await chains.lobster_rewrite_vlm(
            source_text=source if not is_url else f"视频链接：{source}",
            style=style,
            understanding=understanding,
            audio=audio,
            character_name=char_name,
        )
        ok, reason = content_guard(scripts)
        if not ok:
            await send_text(cid, f"内容被拦截：{reason}")
            return

        evaluation = await chains.lobster_evaluate(scripts)
        if not evaluation.get("plans"):
            raise RuntimeError("评估链未返回可用方案")
        msg, _ = chains.format_evaluation(evaluation)
        await send_text(cid, msg)
        _save_session(cid, scripts=scripts, evaluation=evaluation,
                      style_name=_current_style, current_theme=source, source="rewrite_vlm")

    finally:
        if tmp_dir:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


async def _run_rewrite_vlm_from_feishu(cid: str, msg_id: str, file_key: str, msg_type: str = "media") -> None:
    """处理飞书视频/文件消息：下载后自动走 VLM 改编链。"""
    # file_v3_ 前缀是新版文件存储格式，无论 media/file 消息都用 type=file 下载
    # 旧版 video_key 格式才用 type=video
    resource_type = "video" if file_key.startswith("video_key") else "file"
    tmp_dir = tempfile.mkdtemp(prefix="feishu_video_")
    try:
        save_path = os.path.join(tmp_dir, "feishu_video.mp4")
        await send_text(cid, "收到视频，正在下载并分析（多帧 VLM）...")
        await download_file(msg_id, file_key, save_path, resource_type=resource_type)

        style = _get_style()
        await send_text(cid, "正在用 GLM-4V 分析视频画面（6 帧） + librosa/Whisper 分析 BGM...")
        understanding, audio = await asyncio.gather(
            chains.analyze_video_with_vlm(save_path, num_frames=6),
            analyze_audio(save_path),
            return_exceptions=False,
        )
        audio_summary = (
            f"  BGM：{audio.bpm} BPM（{audio.tempo_label}）"
            f"{'，有人声' if audio.has_vocals else '，纯BGM'}"
            if audio.has_audio else "  BGM：无音轨"
        )
        await send_text(
            cid,
            f"视频理解完成：\n"
            f"  类型：{understanding.video_type}/{understanding.sub_type or '-'}（能量{understanding.energy_level or '-'}）\n"
            f"  人物：{understanding.character_appearance[:60]}\n"
            f"  行为：{understanding.core_action[:60]}\n"
            f"  场景：{understanding.setting[:60]}\n"
            f"{audio_summary}\n"
            f"开始改写...",
        )

        char_name = ""
        if _current_character:
            _c = get_character(_current_character)
            char_name = _c.display_name if _c else _current_character

        scripts = await chains.lobster_rewrite_vlm(
            source_text="（飞书上传视频）",
            style=style,
            understanding=understanding,
            audio=audio,
            character_name=char_name,
        )
        ok, reason = content_guard(scripts)
        if not ok:
            await send_text(cid, f"内容被拦截：{reason}")
            return

        evaluation = await chains.lobster_evaluate(scripts)
        if not evaluation.get("plans"):
            raise RuntimeError("评估链未返回可用方案")
        msg, _ = chains.format_evaluation(evaluation)
        await send_text(cid, msg)
        _save_session(cid, scripts=scripts, evaluation=evaluation,
                      style_name=_current_style, current_theme="飞书视频", source="rewrite_vlm")
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
