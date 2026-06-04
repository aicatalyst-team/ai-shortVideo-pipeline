"""火山引擎·豆包 TTS 语音合成模块

通过 WebSocket V3 双向流式协议调用豆包大模型语音合成 2.0，支持多音色。
"""
from __future__ import annotations

import asyncio
import json
import uuid
import struct
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import websockets

from config.settings import get_settings
from core.langfuse_client import observe

logger = logging.getLogger(__name__)

# ── 可用音色 ──
VOICE_PRESETS: dict[str, dict] = {
    # ── 角色 IP 音色（保留） ──
    "su_wan": {
        "voice_type": "zh_female_tianmeiyueyue_uranus_bigtts",
        "name": "苏晚",
        "desc": "温柔知性女声（情感故事首选）",
    },
    "lin_yue": {
        "voice_type": "zh_female_qingchezizi_uranus_bigtts",
        "name": "林悦",
        "desc": "书卷气女声",
    },
    "chen_xing": {
        "voice_type": "zh_female_qinqienv_uranus_bigtts",
        "name": "陈星",
        "desc": "活泼元气女声",
    },
    "ye_cheng": {
        "voice_type": "zh_female_sophie_uranus_bigtts",
        "name": "叶澄",
        "desc": "清冷酷飒女声",
    },
    # ── 解说类音色（Phase 4 新增） ──
    "narrator_male": {
        "voice_type": "zh_male_aojiaobazong_uranus_bigtts",
        "name": "沉稳男声",
        "desc": "磁性男旁白（热搜解说/奇闻首选）",
    },
    "narrator_male_sharp": {
        "voice_type": "zh_male_jingqiangkanye_moon_bigtts",
        "name": "犀利男声",
        "desc": "快节奏犀利旁白（社会观察首选）",
    },
    "narrator_female_calm": {
        "voice_type": "zh_female_sajiaonvyou_moon_bigtts",
        "name": "知性女声",
        "desc": "沉稳知性女旁白（知识科普首选）",
    },
}

DEFAULT_VOICE = "narrator_male"

# ── V3 双向流式协议常量 ──
WS_URL = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"

EVENT_START_CONNECTION = 1
EVENT_FINISH_CONNECTION = 2
EVENT_CONNECTION_STARTED = 50
EVENT_CONNECTION_FAILED = 51
EVENT_START_SESSION = 100
EVENT_FINISH_SESSION = 102
EVENT_SESSION_STARTED = 150
EVENT_SESSION_FINISHED = 152
EVENT_SESSION_FAILED = 153
EVENT_TASK_REQUEST = 200

MSG_FULL_SERVER = 0b1001
MSG_AUDIO_ONLY = 0b1011
MSG_ERROR = 0b1111

WS_TIMEOUT_SEC = 30

# MP3 128 kbps → 16 bytes/ms，用于时间戳缺失时的兜底估算
_MP3_BYTES_PER_MS = 16


@dataclass
class WordTimestamp:
    word: str
    start_ms: int
    end_ms: int


@dataclass
class TTSResult:
    audio_path: Path
    duration_ms: int
    voice_type: str
    text: str
    word_timestamps: list[WordTimestamp] = field(default_factory=list)


def _build_v3_frame(event: int, payload_json: dict | None = None, session_id: str = "") -> bytes:
    """构建 V3 客户端请求帧
    连接级 (event<100): header(4) + event(4) + payload_size(4) + payload
    会话级 (event>=100): header(4) + event(4) + sid_size(4) + sid + payload_size(4) + payload
    """
    header = bytes([0x11, 0x14, 0x10, 0x00])

    if payload_json is not None:
        payload_bytes = json.dumps(payload_json, ensure_ascii=False).encode("utf-8")
    else:
        payload_bytes = b"{}"

    parts = [header, struct.pack(">i", event)]

    if event >= 100:
        sid_bytes = session_id.encode("utf-8")
        parts.append(struct.pack(">I", len(sid_bytes)))
        parts.append(sid_bytes)

    parts.append(struct.pack(">I", len(payload_bytes)))
    parts.append(payload_bytes)
    return b"".join(parts)


def _parse_v3_frame(data: bytes) -> dict:
    """解析 V3 服务端响应帧"""
    if len(data) < 4:
        return {"msg_type": -1}

    msg_type = (data[1] >> 4) & 0x0F
    msg_flags = data[1] & 0x0F
    serialization = (data[2] >> 4) & 0x0F

    result: dict = {"msg_type": msg_type}
    offset = 4

    if msg_flags & 0b0100 and len(data) >= offset + 4:
        result["event"] = struct.unpack(">i", data[offset:offset + 4])[0]
        offset += 4
    elif msg_type == MSG_ERROR and len(data) >= offset + 4:
        result["error_code"] = struct.unpack(">I", data[offset:offset + 4])[0]
        offset += 4

    event = result.get("event", 0)
    if event >= 100 and len(data) >= offset + 4:
        sid_len = struct.unpack(">I", data[offset:offset + 4])[0]
        offset += 4
        offset += sid_len

    if len(data) >= offset + 4:
        payload_len = struct.unpack(">I", data[offset:offset + 4])[0]
        offset += 4
        payload_data = data[offset:offset + payload_len]

        if msg_type == MSG_AUDIO_ONLY:
            result["audio_data"] = payload_data
        elif serialization == 1:
            try:
                result["payload"] = json.loads(payload_data)
            except (json.JSONDecodeError, UnicodeDecodeError):
                result["payload_raw"] = payload_data.hex()[:200]

    return result


async def _recv_until(ws, target_events: set[int], label: str) -> dict:
    """接收帧直到收到目标 event，遇到错误立即抛异常"""
    while True:
        data = await ws.recv()
        if isinstance(data, str):
            continue
        parsed = _parse_v3_frame(data)
        msg_type = parsed.get("msg_type", 0)
        event = parsed.get("event", 0)

        if msg_type == MSG_ERROR:
            raise RuntimeError(f"TTS {label} 失败: {parsed}")
        if event in (EVENT_SESSION_FAILED, EVENT_CONNECTION_FAILED):
            payload = parsed.get("payload", {})
            raise RuntimeError(f"TTS {label} 失败: {payload}")
        if event in target_events:
            return parsed


def _extract_word_timestamps(payloads: list[dict]) -> list[WordTimestamp]:
    """从服务端 MSG_FULL_SERVER JSON 帧中提取字级时间戳。

    兼容两种格式：
      格式1（句级）: {"sentences": [{"words": [{"text": "你", "start_time": 0, "end_time": 200}]}]}
      格式2（扁平）: {"words": [{"text": "你", "start_time": 0, "end_time": 200}]}
    单位：毫秒（服务端返回 ms 时直接用，返回 0.xxx 秒时自动转换）
    """
    timestamps: list[WordTimestamp] = []

    for payload in payloads:
        # 格式 1：句级嵌套
        for sentence in payload.get("sentences", []):
            for w in sentence.get("words", []):
                ts = _word_from_raw(w)
                if ts:
                    timestamps.append(ts)
        # 格式 2：扁平
        for w in payload.get("words", []):
            ts = _word_from_raw(w)
            if ts:
                timestamps.append(ts)

    if not timestamps:
        logger.debug("TTS：服务端未返回字级时间戳，payloads=%s", payloads[:2])
        return []

    # 去重（相同 word+start_ms 的条目只保留一个）
    seen: set[tuple[str, int]] = set()
    deduped: list[WordTimestamp] = []
    for t in timestamps:
        key = (t.word, t.start_ms)
        if key not in seen:
            seen.add(key)
            deduped.append(t)

    return sorted(deduped, key=lambda t: t.start_ms)


def _word_from_raw(w: dict) -> WordTimestamp | None:
    """将服务端单字/词条目转换为 WordTimestamp，自动处理秒/毫秒单位差异。"""
    text = w.get("text", "").strip()
    if not text:
        return None

    start_raw = w.get("start_time", 0)
    end_raw = w.get("end_time", start_raw + 200)

    # 服务端有时返回浮点秒数（< 1000 时大概率是秒）
    if isinstance(start_raw, float) and start_raw < 1000:
        start_ms = int(start_raw * 1000)
        end_ms = int(end_raw * 1000)
    else:
        start_ms = int(start_raw)
        end_ms = int(end_raw)

    return WordTimestamp(word=text, start_ms=start_ms, end_ms=end_ms)


def _estimate_duration_ms(audio_bytes: bytes) -> int:
    """从 MP3 字节数粗估时长（128 kbps 假设，误差约 ±5%）。"""
    if not audio_bytes:
        return 0
    return max(1, len(audio_bytes) // _MP3_BYTES_PER_MS)


def _probe_audio_duration_ms(audio_path: Path | str) -> int:
    """Use ffprobe to read the real audio duration in milliseconds."""
    path = Path(audio_path)
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            return 0
        duration_sec = float((result.stdout or "").strip())
    except Exception as exc:
        logger.warning("ffprobe 读取音频时长失败: %s", exc)
        return 0
    if duration_sec <= 0:
        return 0
    return int(duration_sec * 1000)


@observe(name="tts_synthesize", as_type="span")
async def synthesize(
    text: str,
    output_path: Path | str,
    voice: str = "",
    voice_type: str = "",
    speed: float = 1.0,
    volume: float = 1.0,
    pitch: float = 1.0,
    emotion: str = "",
    with_timestamps: bool = True,
) -> TTSResult:
    """将文本合成为语音文件（V3 双向流式协议）。

    with_timestamps=True（默认开启）：
      在 req_params 里传 enable_timestamp=True，收集服务端 MSG_FULL_SERVER
      JSON 帧，从中解析字级时间戳。若服务端未返回，word_timestamps 为空列表，
      不影响音频生成。
    """
    settings = get_settings()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not voice_type:
        preset_key = voice or DEFAULT_VOICE
        preset = VOICE_PRESETS.get(preset_key)
        if not preset:
            raise ValueError(f"Unknown voice preset: {preset_key}, available: {list(VOICE_PRESETS)}")
        voice_type = preset["voice_type"]

    token = settings.volcengine_tts_access_token
    if not token:
        raise RuntimeError("TTS 凭证缺失: access_token 为空")

    logger.info("TTS 开始: voice=%s, text=%d字, timestamps=%s", voice_type, len(text), with_timestamps)

    session_id = uuid.uuid4().hex[:12]

    ws_headers = {
        "X-Api-Key": token,
        "X-Api-Resource-Id": "seed-tts-2.0",
    }

    start_session_payload = {
        "event": EVENT_START_SESSION,
        "namespace": "BidirectionalTTS",
        "req_params": {
            "model": "seed-tts-2.0-standard",
            "speaker": voice_type,
            "audio_params": {
                "format": "mp3",
                "sample_rate": 24000,
            },
        },
    }

    task_req_params: dict = {"text": text}
    if with_timestamps:
        # 火山引擎 Seed-TTS 2.0 开启字级时间戳
        task_req_params["enable_timestamp"] = True

    task_request_payload = {
        "event": EVENT_TASK_REQUEST,
        "namespace": "BidirectionalTTS",
        "req_params": task_req_params,
    }

    audio_chunks: list[bytes] = []
    full_server_payloads: list[dict] = []

    try:
        async with asyncio.timeout(WS_TIMEOUT_SEC):
            async with websockets.connect(WS_URL, additional_headers=ws_headers) as ws:
                # 1. StartConnection
                await ws.send(_build_v3_frame(EVENT_START_CONNECTION))
                await _recv_until(ws, {EVENT_CONNECTION_STARTED}, "StartConnection")

                # 2. StartSession
                await ws.send(_build_v3_frame(EVENT_START_SESSION, start_session_payload, session_id))
                await _recv_until(ws, {EVENT_SESSION_STARTED}, "StartSession")

                # 3. TaskRequest
                await ws.send(_build_v3_frame(EVENT_TASK_REQUEST, task_request_payload, session_id))

                # 4. FinishSession
                await ws.send(_build_v3_frame(EVENT_FINISH_SESSION, session_id=session_id))

                # 5. 接收音频流 + 时间戳帧
                while True:
                    try:
                        response = await ws.recv()
                    except websockets.exceptions.ConnectionClosed:
                        break

                    if isinstance(response, str):
                        continue

                    parsed = _parse_v3_frame(response)
                    msg_type = parsed.get("msg_type", 0)
                    event = parsed.get("event", 0)

                    if msg_type == MSG_AUDIO_ONLY and "audio_data" in parsed:
                        audio_chunks.append(parsed["audio_data"])

                    elif msg_type == MSG_FULL_SERVER:
                        if "payload" in parsed:
                            full_server_payloads.append(parsed["payload"])
                            logger.debug("TTS MSG_FULL_SERVER payload keys: %s",
                                         list(parsed["payload"].keys()))
                        # MSG_FULL_SERVER 携带 SESSION_FINISHED 时结束循环
                        if event == EVENT_SESSION_FAILED:
                            raise RuntimeError(f"TTS SessionFailed: {parsed.get('payload', {})}")
                        if event == EVENT_SESSION_FINISHED:
                            break

                    elif msg_type == MSG_ERROR:
                        raise RuntimeError(f"TTS 音频流错误: {parsed}")

                    elif event in (EVENT_SESSION_FINISHED, EVENT_SESSION_FAILED, EVENT_CONNECTION_FAILED):
                        if event == EVENT_SESSION_FAILED:
                            raise RuntimeError(f"TTS SessionFailed: {parsed.get('payload', {})}")
                        break

    except asyncio.TimeoutError:
        raise RuntimeError(f"TTS WebSocket 超时 ({WS_TIMEOUT_SEC}s)")
    except websockets.exceptions.WebSocketException as e:
        raise RuntimeError(f"TTS WebSocket 错误: {type(e).__name__}: {e}") from e

    if not audio_chunks:
        raise RuntimeError("TTS 返回空音频数据")

    audio_data = b"".join(audio_chunks)
    output_path.write_bytes(audio_data)

    # 解析字级时间戳
    word_timestamps: list[WordTimestamp] = []
    if with_timestamps and full_server_payloads:
        word_timestamps = _extract_word_timestamps(full_server_payloads)

    # 优先用时间戳末尾推算时长，兜底用字节估算
    if word_timestamps:
        duration_ms = word_timestamps[-1].end_ms
    else:
        probed_duration_ms = _probe_audio_duration_ms(output_path)
        estimated_duration_ms = _estimate_duration_ms(audio_data)
        duration_ms = probed_duration_ms or estimated_duration_ms
        if probed_duration_ms:
            logger.info(
                "TTS 未返回时间戳，使用 ffprobe 实测音频时长: %.2fs (字节估算 %.2fs)",
                probed_duration_ms / 1000.0,
                estimated_duration_ms / 1000.0,
            )

    logger.info(
        "TTS 完成: %s, voice=%s, %d bytes, duration=%dms, timestamps=%d字",
        output_path, voice_type, len(audio_data), duration_ms, len(word_timestamps),
    )

    return TTSResult(
        audio_path=output_path,
        duration_ms=duration_ms,
        voice_type=voice_type,
        text=text,
        word_timestamps=word_timestamps,
    )


async def whisper_fallback_timestamps(
    audio_path: Path | str,
    language: str = "zh",
) -> list[WordTimestamp]:
    """Whisper ASR 兜底：当 TTS 未返回时间戳时，用本地 Whisper 转写获取字级时间戳。

    需要 `openai-whisper` 或 `faster-whisper` 包已安装。
    若两者均不可用，返回空列表（调用方降级为均分估算）。
    """
    audio_path = Path(audio_path)

    # 优先尝试 faster-whisper（速度更快）
    try:
        from faster_whisper import WhisperModel  # type: ignore
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(
            str(audio_path),
            language=language,
            word_timestamps=True,
        )
        result: list[WordTimestamp] = []
        for seg in segments:
            for w in (seg.words or []):
                result.append(WordTimestamp(
                    word=w.word.strip(),
                    start_ms=int(w.start * 1000),
                    end_ms=int(w.end * 1000),
                ))
        logger.info("Whisper(faster) 转写完成: %d 字", len(result))
        return result
    except ImportError:
        pass
    except Exception as e:
        logger.warning("faster-whisper 转写失败: %s", e)

    # 备选：openai-whisper
    try:
        import whisper  # type: ignore
        model = whisper.load_model("base")
        out = model.transcribe(str(audio_path), language=language, word_timestamps=True)
        result = []
        for seg in out.get("segments", []):
            for w in seg.get("words", []):
                result.append(WordTimestamp(
                    word=w["word"].strip(),
                    start_ms=int(w["start"] * 1000),
                    end_ms=int(w["end"] * 1000),
                ))
        logger.info("Whisper(openai) 转写完成: %d 字", len(result))
        return result
    except ImportError:
        logger.warning("Whisper 未安装（pip install faster-whisper 或 openai-whisper），跳过 ASR 兜底")
    except Exception as e:
        logger.warning("openai-whisper 转写失败: %s", e)

    return []


async def synthesize_with_fallback(
    text: str,
    output_path: Path | str,
    voice: str = "",
    voice_type: str = "",
    speed: float = 1.0,
    volume: float = 1.0,
    pitch: float = 1.0,
    emotion: str = "",
) -> TTSResult:
    """synthesize 的包装版本，自动使用 Whisper 兜底补全时间戳。"""
    result = await synthesize(
        text=text,
        output_path=output_path,
        voice=voice,
        voice_type=voice_type,
        speed=speed,
        volume=volume,
        pitch=pitch,
        emotion=emotion,
        with_timestamps=True,
    )

    if not result.word_timestamps:
        logger.info("TTS 未返回时间戳，启动 Whisper ASR 兜底")
        fallback = await whisper_fallback_timestamps(result.audio_path)
        if fallback:
            duration_ms = max(result.duration_ms, fallback[-1].end_ms)
            result = TTSResult(
                audio_path=result.audio_path,
                duration_ms=duration_ms,
                voice_type=result.voice_type,
                text=result.text,
                word_timestamps=fallback,
            )

    return result


async def list_voices() -> list[dict]:
    """返回可用音色列表"""
    return [
        {"key": k, **v}
        for k, v in VOICE_PRESETS.items()
    ]
