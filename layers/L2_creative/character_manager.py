from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from config.settings import get_settings

log = logging.getLogger(__name__)


@dataclass
class Identity:
    age: str = ""
    profession: str = ""
    personality: str = ""


@dataclass
class Appearance:
    hair: str = ""
    face: str = ""
    body: str = ""


@dataclass
class Wardrobe:
    casual: str = ""
    formal: str = ""
    winter: str = ""


@dataclass
class Props:
    items: list[str] = field(default_factory=list)


@dataclass
class Voice:
    tts_id: str = ""
    pace: str = ""
    emotion: str = ""


@dataclass
class VisualRefs:
    front: str = ""
    side: str = ""
    profile_3_4: str = ""
    back: str = ""
    closeup: str = ""


@dataclass
class Position:
    # 主体在画面里的站位
    subject_position: Literal[
        "center", "front", "back",
        "left", "right",
        "left_front", "right_front", "left_back", "right_back",
    ] = "center"

    # 镜头景别
    camera_distance: Literal[
        "extreme_close", "close_up", "medium_close",
        "medium", "medium_wide", "wide", "extreme_wide",
        "over_shoulder",
    ] = "medium"

    # 镜头角度
    camera_angle: Literal[
        "eye_level", "low_angle", "high_angle", "dutch", "birds_eye", "worms_eye",
    ] = "eye_level"


@dataclass
class CharacterProfile:
    key: str
    display_name: str
    description: str
    visual_tags: str
    ref_images: dict[str, str] = field(default_factory=dict)
    compatible_styles: list[str] = field(default_factory=list)
    max_consecutive_shots: int = 4

    # R1.1（W2 D8）新增 6 类字段。旧消费方不感知；新字段均有默认空值，访问 .X.Y 不会 AttributeError
    identity: Identity = field(default_factory=Identity)
    appearance: Appearance = field(default_factory=Appearance)
    wardrobe: Wardrobe = field(default_factory=Wardrobe)
    props: Props = field(default_factory=Props)
    voice: Voice = field(default_factory=Voice)
    visual_refs: VisualRefs = field(default_factory=VisualRefs)

    def front_ref_path(self) -> Path | None:
        return self._resolve("front")

    def side_ref_path(self) -> Path | None:
        return self._resolve("side")

    def best_ref_path(self) -> Path | None:
        return self.front_ref_path() or self.side_ref_path()

    def _resolve(self, key: str) -> Path | None:
        rel = self.ref_images.get(key)
        if not rel:
            return None
        base = Path(get_settings().characters_config_path).parent
        p = base / rel
        return p if p.is_file() else None


def _load_identity(d: dict) -> Identity:
    if not isinstance(d, dict):
        return Identity()
    return Identity(
        age=str(d.get("age", "")),
        profession=str(d.get("profession", "")),
        personality=str(d.get("personality", "")),
    )


def _load_appearance(d: dict) -> Appearance:
    if not isinstance(d, dict):
        return Appearance()
    return Appearance(
        hair=str(d.get("hair", "")),
        face=str(d.get("face", "")),
        body=str(d.get("body", "")),
    )


def _load_wardrobe(d: dict) -> Wardrobe:
    if not isinstance(d, dict):
        return Wardrobe()
    return Wardrobe(
        casual=str(d.get("casual", "")),
        formal=str(d.get("formal", "")),
        winter=str(d.get("winter", "")),
    )


def _load_props(d: dict) -> Props:
    if not isinstance(d, dict):
        return Props()
    items = d.get("items", [])
    if not isinstance(items, list):
        items = []
    return Props(items=[str(x) for x in items])


def _load_voice(d: dict) -> Voice:
    if not isinstance(d, dict):
        return Voice()
    return Voice(
        tts_id=str(d.get("tts_id", "")),
        pace=str(d.get("pace", "")),
        emotion=str(d.get("emotion", "")),
    )


def _load_visual_refs(d: dict) -> VisualRefs:
    if not isinstance(d, dict):
        return VisualRefs()
    return VisualRefs(
        front=str(d.get("front", "")),
        side=str(d.get("side", "")),
        profile_3_4=str(d.get("profile_3_4", "")),
        back=str(d.get("back", "")),
        closeup=str(d.get("closeup", "")),
    )


_cache: dict[str, CharacterProfile] | None = None
_default_key: str = ""


def _load_characters(force: bool = False) -> dict[str, CharacterProfile]:
    global _cache, _default_key
    if _cache is not None and not force:
        return _cache

    cfg_path = Path(get_settings().characters_config_path)
    if not cfg_path.is_file():
        log.warning("角色配置文件不存在: %s", cfg_path)
        _cache = {}
        return _cache

    with open(cfg_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    _default_key = raw.pop("default_character", "")
    _cache = {}

    for key, data in raw.items():
        if not isinstance(data, dict):
            continue
        try:
            tags = data.get("visual_tags", "")
            if isinstance(tags, str):
                tags = " ".join(tags.split())
            _cache[key] = CharacterProfile(
                key=key,
                display_name=data.get("display_name", key),
                description=data.get("description", "").strip(),
                visual_tags=tags,
                ref_images=data.get("ref_images", {}),
                compatible_styles=data.get("compatible_styles", []),
                max_consecutive_shots=data.get("max_consecutive_shots", 4),
                identity=_load_identity(data.get("identity", {})),
                appearance=_load_appearance(data.get("appearance", {})),
                wardrobe=_load_wardrobe(data.get("wardrobe", {})),
                props=_load_props(data.get("props", {})),
                voice=_load_voice(data.get("voice", {})),
                visual_refs=_load_visual_refs(data.get("visual_refs", {})),
            )
            log.info("已加载角色: %s (%s)", key, _cache[key].display_name)
        except Exception as e:
            log.error("加载角色失败 %s: %s", key, e)

    return _cache


def get_character(name: str) -> CharacterProfile | None:
    chars = _load_characters()
    if name in chars:
        return chars[name]
    for c in chars.values():
        if c.display_name == name:
            return c
    return None


def get_default_character() -> CharacterProfile | None:
    chars = _load_characters()
    if _default_key and _default_key in chars:
        return chars[_default_key]
    if chars:
        return next(iter(chars.values()))
    return None


def list_characters() -> list[CharacterProfile]:
    return list(_load_characters().values())


def get_characters_for_style(style_name: str) -> list[CharacterProfile]:
    return [
        c for c in _load_characters().values()
        if not c.compatible_styles or style_name in c.compatible_styles
    ]


def resolve_operator_to_character(operator_name: str, style_name: str = "") -> CharacterProfile | None:
    char = get_character(operator_name)
    if char:
        return char
    compatible = get_characters_for_style(style_name) if style_name else list_characters()
    return compatible[0] if compatible else get_default_character()


def match_character_by_appearance(appearance_desc: str) -> CharacterProfile | None:
    """根据 VLM 识别的外观描述，尝试匹配已有角色（S2.6）。

    匹配逻辑：对比外观描述与各角色 visual_tags 的关键词重叠度。
    重叠 >= 2 个关键词才认为匹配，避免误匹配。
    """
    if not appearance_desc:
        return None

    desc_lower = appearance_desc.lower()
    # 提取外观关键词（发色/服装/体态等）
    keywords = [w for w in desc_lower.split() if len(w) >= 3]

    best_char: CharacterProfile | None = None
    best_score = 0

    for char in _load_characters().values():
        tags_lower = char.visual_tags.lower()
        score = sum(1 for kw in keywords if kw in tags_lower)
        if score > best_score:
            best_score = score
            best_char = char

    if best_score >= 2:
        log.info("[角色匹配] 匹配到 %s (score=%d)", best_char.display_name, best_score)
        return best_char

    log.info("[角色匹配] 无匹配角色 (best_score=%d < 2)", best_score)
    return None


def make_temp_character(
    appearance_desc: str,
    first_frame_path: "Path | str",
) -> CharacterProfile:
    """无法匹配时，用首帧图片创建临时角色（S2.6）。

    临时角色以首帧作为参考图，保证后续生图/生视频的外观一致性。
    key 固定为 '__temp__'，不会被持久化到 characters.yaml。
    """
    from pathlib import Path as _Path
    first_frame_path = _Path(first_frame_path)

    log.info("[角色匹配] 创建临时角色，首帧参考: %s", first_frame_path.name)

    return CharacterProfile(
        key="__temp__",
        display_name="临时角色",
        description=appearance_desc,
        visual_tags=appearance_desc,
        ref_images={"front": str(first_frame_path)},
        compatible_styles=[],
    )


def match_or_create_temp_character(
    appearance_desc: str,
    first_frame_path: "Path | str",
) -> CharacterProfile:
    """VLM 改编模式的角色解析入口（S2.6）。

    先尝试匹配已有角色；无匹配时用首帧创建临时角色。
    调用方拿到 CharacterProfile 后直接传给 generate_clip() 即可。
    """
    matched = match_character_by_appearance(appearance_desc)
    if matched:
        return matched
    return make_temp_character(appearance_desc, first_frame_path)
