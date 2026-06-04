from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass
class VideoUnderstanding:
    """VLM 对视频的理解结果。

    character_appearance 和 core_action 是锁定字段——改编时必须保留。
    video_type + sub_type + energy_level 是下游改写链的核心路由字段。
    """
    video_type: str            # 视频类型：跳舞/唱歌/吃播/Vlog/穿搭/健身/美妆/解说/剧情/其他
    sub_type: str              # 子类型：热舞/街舞/古典舞/抒情舞/民族舞/芭蕾/宅舞/爵士舞/韩团舞...
    energy_level: str          # 动作强度：极低/低/中/高/极高
    character_appearance: str  # 角色外观：发色/服装/体态等（改编时强制保留）
    core_action: str           # 核心动作（必须反映 video_type+sub_type，禁止弱化）
    movement_rhythm: str       # 动作节奏感（用于推断 BGM 节奏）
    setting: str               # 场景环境：室内/室外/时代背景
    emotion: str               # 情绪基调：欢快/压抑/紧张/温暖（必须与 sub_type 一致）
    key_message: str           # 核心信息/主旨：这段内容想传达什么


@dataclass
class AudioUnderstanding:
    """对原视频音频/BGM 的分析结果（FFmpeg 抽音 + librosa BPM + Whisper 歌词）。"""
    has_audio: bool         # 视频是否有音轨
    bpm: float              # 节拍数（每分钟）
    tempo_label: str        # 节奏档：未知/慢/中/快/超快
    energy_db: float        # 平均能量 dB（>-30 算响亮，<-50 算很安静）
    has_vocals: bool        # 是否检测到人声/歌词
    lyrics_excerpt: str     # 歌词或语音转写前 200 字
    language: str           # 语言代码（zh/en/ja/...）
    duration_sec: float     # 音频时长（秒）


def parse_video_understanding(raw: str) -> VideoUnderstanding:
    """从 GLM-4V 返回的 JSON 字符串解析 VideoUnderstanding。

    GLM-4V 不一定输出严格 JSON，做最大容错处理。
    """
    data = parse_json_object(raw)
    return VideoUnderstanding(
        video_type=data.get("video_type", "其他").strip(),
        sub_type=data.get("sub_type", "").strip(),
        energy_level=data.get("energy_level", "").strip(),
        character_appearance=data.get("character_appearance", "").strip(),
        core_action=data.get("core_action", "").strip(),
        movement_rhythm=data.get("movement_rhythm", "").strip(),
        setting=data.get("setting", "").strip(),
        emotion=data.get("emotion", "").strip(),
        key_message=data.get("key_message", "").strip(),
    )


def _strip_code_fence(raw: str) -> str:
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", raw.strip())
    stripped = re.sub(r"\n?```\s*$", "", stripped)
    return stripped.strip()


def parse_json_array(raw: str) -> list[dict]:
    """Extract a JSON array from LLM output, tolerating markdown code fences and truncation."""
    cleaned = _strip_code_fence(raw)
    # 尝试直接解析
    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return result
    except Exception:
        pass
    # 正则提取
    match = re.search(r"\[[\s\S]+\]", cleaned)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    # 截断修复：找到最后一个完整的 },] 并闭合
    last_obj = cleaned.rfind("}")
    if last_obj > 0:
        attempt = cleaned[:last_obj + 1]
        if not attempt.rstrip().endswith("]"):
            attempt = attempt.rstrip().rstrip(",") + "]"
        try:
            result = json.loads(attempt)
            if isinstance(result, list):
                return result
        except Exception:
            pass
    return []


def parse_json_object(raw: str) -> dict:
    """Extract a JSON object from LLM output, with truncation repair."""
    cleaned = _strip_code_fence(raw)
    # 直接解析
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except Exception:
        pass
    # 正则提取完整对象
    match = re.search(r"\{[\s\S]+\}", cleaned)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    # 截断修复：找到 { 开头，尝试补全
    brace = cleaned.find("{")
    if brace >= 0:
        fragment = cleaned[brace:]
        # 如果最后一个值是被截断的字符串，关闭它
        # 找最后一个完整的 key-value pair
        last_quote = fragment.rfind('"')
        if last_quote > 0:
            # 检查引号是否未闭合（奇数个引号）
            before = fragment[:last_quote + 1]
            quote_count = before.count('"')
            if quote_count % 2 != 0:
                fragment = before + '"}'
            else:
                fragment = before + "}"
            # 清理尾部多余逗号
            fragment = re.sub(r',\s*"?\s*}', "}", fragment)
            try:
                result = json.loads(fragment)
                if isinstance(result, dict):
                    return result
            except Exception:
                pass
    return {}
