from __future__ import annotations

import re


TEXTLESS_VISUAL_GUARD = (
    "premium cinematic scene, abstract geometric light overlays only, blank glass and "
    "unmarked surfaces, no readable text, no letters, no numbers, no subtitles, "
    "no captions, no UI words, no screen text, no logos, no brand marks, no pseudo text, "
    "no gibberish letters, no mirrored text, no reversed text, no misspelled words"
)

TEXTLESS_VISUAL_GUARD_SHORT = (
    "premium cinematic scene, text-free visuals, abstract light overlays only, "
    "blank glass, no logos, no UI, no glyphs, no brand marks"
)

TEXTLESS_NEGATIVE_PROMPT = (
    "readable text, letters, numbers, subtitles, captions, UI words, screen text, "
    "phone screen text, monitor text, holographic text, data panel text, chart labels, "
    "axis labels, data labels, watermark, logo, brand logo, app icon, fake logo, "
    "pseudo text, gibberish text, garbled letters, malformed typography, mirrored text, "
    "reversed text, misspelled words, fake UI, HUD overlay, holographic HUD, "
    "transparent data panel, floating interface, dashboard, screenshot UI, hologram, "
    "projection, glass panel, sci-fi screen, futuristic interface, laboratory monitor, "
    "control room display, medical monitor, diagnostic readout, file path, debug overlay, "
    "timestamp overlay"
)

_TEXT_TRIGGER_REPLACEMENTS: list[tuple[str, str]] = [
    (
        r"\b(Google|Gemini|Chrome|Apple|MacBook|Mac|iPhone|iPad|Android|OpenAI|Microsoft|Windows|Bing)\b",
        "generic unbranded physical object",
    ),
    (
        r"(谷歌|苹果|麦克|微软|安卓|浏览器|搜索引擎|品牌|商标)",
        "unbranded object",
    ),
    (
        r"\b(search\s*(page|engine|box|bar|result|results)|browser|webpage|website|homepage)\b",
        "real-world scene without visible interface",
    ),
    (
        r"(搜索页面|搜索框|搜索结果|网页|网站|主页|页面|信息流|摘要卡|链接)",
        "real-world scene without visible interface",
    ),
    (
        r"\b(HUD|UI|GUI|interface|dashboard|control panel|data panel|floating panel|transparent panel|transparent data panel|display panel|analysis panel|screen|display|monitor|terminal|overlay|readout|readouts)\b",
        "abstract geometric light overlay without glyphs",
    ),
    (
        r"\b(hologram|holographic|projection|augmented reality|AR interface|scanning interface|scanner readout|data stream)\b",
        "abstract geometric light streaks without glyphs",
    ),
    (
        r"(全息|悬浮界面|透明面板|数据面板|科技面板|控制面板|界面|屏幕|手机屏幕|电脑屏幕|仪表盘|扫描界面|投影文字|数据流)",
        "abstract light effect",
    ),
    (
        r"\b(logo|brand mark|app icon|icon|badge|wordmark)\b",
        "simple abstract shape",
    ),
    (
        r"(logo|标志|图标|徽标)",
        "simple abstract shape",
    ),
    (
        r"\b(chart|graph|bar chart|line chart|infographic|data visualization|statistics|diagram|information-dense|labels?|titles?|caption|text|typography|word|words)\b",
        "unmarked physical props",
    ),
    (
        r"(图表|柱状图|折线图|数据可视化|信息图|统计|示意图|标签|标题|文字|字幕|字母|字符)",
        "abstract visual elements",
    ),
    (r"\bAI\b", "artificial intelligence concept"),
    (r"\b\d+\s*[pP]\b", "subtle quality cue"),
    (r"\b\d+\s*mm\b", "classic film grain"),
]

_GENERIC_TEXT_PATTERNS = [
    r"""['"“”‘’][^'"“”‘’]{1,40}['"“”‘’]""",
    r"\b\d{1,2}[:：]\d{1,2}\b",
    r"\b[A-Z]{3,}[A-Za-z0-9_-]*\b",
    r"(?<![A-Za-z])\d+(?![A-Za-z])",
]

_PROMPT_COMPRESSION_REPLACEMENTS: list[tuple[str, str]] = [
    (r"\babstract geometric light overlay without glyphs\b", "abstract light overlay"),
    (r"\babstract geometric light overlays only\b", "abstract light overlays"),
    (r"\babstract geometric light streaks without glyphs\b", "abstract light streaks"),
    (r"\breal-world scene without visible interface\b", "real-world scene"),
    (r"\bgeneric unbranded physical object\b", "unbranded object"),
    (r"\bunmarked physical props\b", "unmarked props"),
    (r"\bartificial intelligence concept\b", "ai concept"),
    (r"\bsubtle quality cue\b", "quality cue"),
    (r"\bclean highlights\b", "clean lighting"),
    (r"\bno logo-like symbols\b", "no logos"),
    (r"\bno product branding\b", "no branding"),
    (r"\bno interface shapes with letters\b", "no UI glyphs"),
    (r"\breplace every text-like area with pure geometric light\b", "replace text-like areas with pure light"),
]

_LOW_PRIORITY_SEGMENT_PATTERNS = [
    r"\bpremium\b",
    r"\bcinematic\b",
    r"\bclean (?:lighting|highlights)\b",
    r"\bquality cue\b",
    r"\bclassic film grain\b",
    r"\bsubtle\b",
    r"\balternative\b",
]

_HIGH_PRIORITY_SEGMENT_PATTERNS = [
    r"\b(close-up|close up|portrait|framing|wide shot|medium shot|full body|profile)\b",
    r"\b(camera|angle|composition|silhouette)\b",
]

_MEDIUM_PRIORITY_SEGMENT_PATTERNS = [
    r"\b(expression|gesture|pose)\b",
]


def _split_prompt_guard(text: str) -> tuple[str, str]:
    stripped = str(text or "").strip().rstrip(" ,")
    for guard in (TEXTLESS_VISUAL_GUARD, TEXTLESS_VISUAL_GUARD_SHORT):
        marker = f", {guard}"
        if stripped.endswith(marker):
            return stripped[: -len(marker)].rstrip(" ,"), guard
        if stripped == guard:
            return "", guard
    return stripped, ""


def _normalize_prompt_segment(segment: str) -> str:
    text = str(segment or "").strip(" ,;")
    if not text:
        return ""
    for pattern, repl in _PROMPT_COMPRESSION_REPLACEMENTS:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip(" ,;")


def _dedupe_prompt_segments(segments: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for segment in segments:
        normalized = _normalize_prompt_segment(segment)
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def _join_prompt(body_segments: list[str], guard: str) -> str:
    body = ", ".join(seg for seg in body_segments if seg).strip(" ,")
    if body and guard:
        return f"{body}, {guard}"
    return body or guard


def fit_visual_prompt(prompt: str, *, max_len: int = 2400) -> str:
    body, guard = _split_prompt_guard(prompt)
    body_segments = _dedupe_prompt_segments(re.split(r"\s*,\s*", body)) if body else []
    guard_to_use = guard
    candidate = _join_prompt(body_segments, guard_to_use)
    if len(candidate) <= max_len:
        return candidate

    if guard_to_use == TEXTLESS_VISUAL_GUARD:
        guard_to_use = TEXTLESS_VISUAL_GUARD_SHORT
        candidate = _join_prompt(body_segments, guard_to_use)
        if len(candidate) <= max_len:
            return candidate

    while len(candidate) > max_len and len(body_segments) > 2:
        removable_index = None
        for idx in range(len(body_segments) - 1, -1, -1):
            segment = body_segments[idx]
            if idx == 0:
                continue
            if any(re.search(pattern, segment, flags=re.IGNORECASE) for pattern in _HIGH_PRIORITY_SEGMENT_PATTERNS):
                continue
            if any(re.search(pattern, segment, flags=re.IGNORECASE) for pattern in _LOW_PRIORITY_SEGMENT_PATTERNS):
                removable_index = idx
                break
        if removable_index is None:
            for idx in range(len(body_segments) - 1, -1, -1):
                segment = body_segments[idx]
                if idx == 0:
                    continue
                if any(re.search(pattern, segment, flags=re.IGNORECASE) for pattern in _HIGH_PRIORITY_SEGMENT_PATTERNS):
                    continue
                removable_index = idx
                break
        if removable_index is None:
            removable_index = len(body_segments) - 1
        body_segments.pop(removable_index)
        candidate = _join_prompt(body_segments, guard_to_use)

    if len(candidate) <= max_len:
        return candidate

    if guard_to_use:
        marker = f", {guard_to_use}"
        while len(body_segments) > 1:
            joined_body = ", ".join(body_segments).strip(" ,")
            if len(joined_body) + len(marker) <= max_len:
                return f"{joined_body}{marker}"
            removable_index = None
            for idx in range(len(body_segments) - 1, -1, -1):
                if idx == 0:
                    continue
                segment = body_segments[idx]
                if any(re.search(pattern, segment, flags=re.IGNORECASE) for pattern in _HIGH_PRIORITY_SEGMENT_PATTERNS):
                    continue
                removable_index = idx
                break
            if removable_index is None:
                for idx in range(len(body_segments) - 1, -1, -1):
                    if idx == 0:
                        continue
                    segment = body_segments[idx]
                    if any(re.search(pattern, segment, flags=re.IGNORECASE) for pattern in _MEDIUM_PRIORITY_SEGMENT_PATTERNS):
                        removable_index = idx
                        break
            if removable_index is None:
                removable_index = len(body_segments) - 1
            body_segments.pop(removable_index)
        head_budget = max_len - len(marker)
        if head_budget > 32:
            trimmed_body = body_segments[0][:head_budget].rstrip(" ,")
            return f"{trimmed_body}{marker}"

    return candidate[:max_len].rstrip(" ,")


def sanitize_visual_prompt(prompt: str, *, fallback: str = "") -> str:
    """Strip text-heavy visual triggers and append a textless guard."""
    text = str(prompt or fallback or "").strip()
    if not text:
        return ""

    for pattern, repl in _TEXT_TRIGGER_REPLACEMENTS:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    for pattern in _GENERIC_TEXT_PATTERNS:
        text = re.sub(pattern, "physical visual cue", text)

    text = re.sub(r"\s+", " ", text).strip(" ,;，。")
    lowered = text.lower()
    if "no readable text" not in lowered and "text-free" not in lowered:
        text = f"{text}, {TEXTLESS_VISUAL_GUARD}"
    return fit_visual_prompt(text)
