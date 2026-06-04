"""5.2: image-text validation using GLM-4V."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from integrations.llm_client import call_glm4v

log = logging.getLogger(__name__)


@dataclass
class ValidationScore:
    image_path: str
    prompt_score: float = 0.0
    face_score: float = 0.0
    composite_score: float = 0.0
    raw_response: str = ""


def _parse_score_from_glm_response(raw: str) -> float:
    """Extract a 0-1 float from tolerant GLM text output."""
    if not raw:
        return 0.0
    matches = re.findall(r"(?<![\d.])(?:1(?:\.0+)?|0(?:\.\d+)?)(?![\d.])", raw)
    if matches:
        try:
            score = float(matches[0])
            return max(0.0, min(1.0, score))
        except ValueError:
            pass
    return 0.0


def clip_score(image_path: str | Path, text: str) -> float:
    """Use GLM-4V to score image/prompt semantic consistency."""
    prompt = (
        "你是图文一致性评分器。请对比下面这张图片与文字描述，"
        "评估它们的语义相似度。\n\n"
        f"【文字描述】{text}\n\n"
        "评分标准：\n"
        "- 1.0 = 完全一致（图中所有关键元素都和描述对应）\n"
        "- 0.7 = 大部分一致（主要元素匹配，少量细节差异）\n"
        "- 0.5 = 部分一致（主体匹配，但场景/动作/属性偏差大）\n"
        "- 0.2 = 弱相关（仅个别元素相关）\n"
        "- 0.0 = 完全不相关\n\n"
        "请直接输出 0-1 之间的浮点数，不要解释。例如：0.75"
    )
    try:
        raw = call_glm4v(str(image_path), prompt)
        score = _parse_score_from_glm_response(raw)
        log.info("[clip_score] %s vs prompt -> %.2f", Path(image_path).name, score)
        return score
    except Exception as e:
        log.error("[clip_score] failed: %s", e)
        return 0.0


def face_similarity(image_path: str | Path, ref_image_path: str | Path) -> float:
    """Use GLM-4V grid comparison to score character consistency."""
    from integrations.llm_client import call_glm4v_multi

    prompt = (
        "请对比这两张图片中的人物是否是同一个人（注意：图片可能拼成网格展示）。\n\n"
        "评分标准：\n"
        "- 1.0 = 确定是同一人（面部特征、发型、整体气质一致）\n"
        "- 0.7 = 大概率是同一人（主要特征匹配）\n"
        "- 0.5 = 不确定（部分特征相似）\n"
        "- 0.2 = 大概率不是\n"
        "- 0.0 = 明显不是同一人\n\n"
        "请直接输出 0-1 浮点数。"
    )
    try:
        raw = call_glm4v_multi([str(image_path), str(ref_image_path)], prompt)
        score = _parse_score_from_glm_response(raw)
        log.info("[face_similarity] %s vs ref -> %.2f", Path(image_path).name, score)
        return score
    except Exception as e:
        log.error("[face_similarity] failed: %s", e)
        return 0.0


def composite_score(
    image_path: str | Path,
    prompt: str,
    ref_image_path: str | Path | None = None,
    prompt_weight: float = 0.6,
    face_weight: float = 0.4,
) -> ValidationScore:
    """Combine prompt consistency and optional face similarity."""
    p_score = clip_score(image_path, prompt)

    if ref_image_path and Path(ref_image_path).exists():
        f_score = face_similarity(image_path, ref_image_path)
        composite = prompt_weight * p_score + face_weight * f_score
    else:
        f_score = 0.0
        composite = p_score

    log.info(
        "[composite_score] %s prompt=%.2f face=%.2f -> %.2f",
        Path(image_path).name,
        p_score,
        f_score,
        composite,
    )
    return ValidationScore(
        image_path=str(image_path),
        prompt_score=p_score,
        face_score=f_score,
        composite_score=composite,
    )


def pick_best_candidate(
    candidates: list[str | Path],
    prompt: str,
    ref_image_path: str | Path | None = None,
    min_acceptable_score: float = 0.30,
) -> tuple[str, ValidationScore] | None:
    """Pick the highest composite score, or None when all are below threshold."""
    if not candidates:
        return None

    scored = [(str(c), composite_score(c, prompt, ref_image_path)) for c in candidates]
    best_path, best_score = max(scored, key=lambda x: x[1].composite_score)

    if best_score.composite_score < min_acceptable_score:
        log.warning(
            "[pick_best] all candidates below threshold %.2f, best=%.2f",
            min_acceptable_score,
            best_score.composite_score,
        )
        return None

    log.info("[pick_best] selected %s score=%.2f", Path(best_path).name, best_score.composite_score)
    return best_path, best_score
