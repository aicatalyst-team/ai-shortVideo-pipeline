from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from core.parsers import parse_json_object
from integrations.llm_client import call_glm4v

log = logging.getLogger(__name__)


@dataclass
class TextArtifactReport:
    has_artifacts: bool
    reason: str = ""
    raw_response: str = ""
    confidence: float = 0.0
    artifact_type: str = "none"
    evidence: str = ""


_PROMPT = (
    "You are a calibrated image quality inspector for generated video frames. "
    "Flag ONLY clear visible text artifacts: readable words, obvious random letters, "
    "logo marks, watermarks, chart labels, subtitles, or fake UI labels. Do not flag "
    "abstract light streaks, reflections, furniture edges, decorative shapes, wall "
    "textures, or ambiguous high-tech glow unless distinct letter-like glyphs are "
    "clearly visible.\n\n"
    "Return JSON only with these fields:\n"
    "{\"has_artifacts\": false, \"artifact_type\": \"none\", \"confidence\": 0.0, "
    "\"evidence\": \"\", \"reason\": \"clean or ambiguous\"}\n\n"
    "Use has_artifacts=true only when confidence is at least 0.82 and evidence names "
    "the visible artifact. artifact_type must be one of: readable_text, random_letters, "
    "logo, watermark, subtitle, chart_label, fake_ui_label, none."
)

_VALID_BLOCKING_TYPES = {
    "readable_text",
    "random_letters",
    "logo",
    "watermark",
    "subtitle",
    "chart_label",
    "fake_ui_label",
}


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def inspect_text_artifacts(image_path: str | Path) -> TextArtifactReport:
    """Use GLM-4V to catch garbled letters before sending a frame to video."""
    try:
        raw = call_glm4v(str(image_path), _PROMPT)
        obj = parse_json_object(raw)
        confidence = _to_float(obj.get("confidence"))
        artifact_type = str(obj.get("artifact_type", "none")).strip().lower()
        evidence = str(obj.get("evidence", "")).strip()[:300]
        reason = str(obj.get("reason", "")).strip()[:300]
        raw_has_artifacts = bool(obj.get("has_artifacts"))
        has_blocking_artifacts = (
            raw_has_artifacts
            and confidence >= 0.82
            and artifact_type in _VALID_BLOCKING_TYPES
            and bool(evidence)
        )
        return TextArtifactReport(
            has_artifacts=has_blocking_artifacts,
            reason=reason,
            raw_response=raw,
            confidence=confidence,
            artifact_type=artifact_type,
            evidence=evidence,
        )
    except Exception as exc:
        # Do not fail production generation if the inspector is unavailable.
        log.warning("[text_artifact_guard] inspection skipped: %s", exc)
        return TextArtifactReport(False, f"inspection skipped: {exc}", "")
