from __future__ import annotations

from unittest.mock import patch

from layers.L3_visual.validators import (
    _parse_score_from_glm_response,
    clip_score,
    composite_score,
    pick_best_candidate,
)


def test_clip_score_parses_decimal_from_response():
    with patch("layers.L3_visual.validators.call_glm4v", return_value="Score: 0.8"):
        assert clip_score("image.png", "coffee") == 0.8

    assert _parse_score_from_glm_response("0.75") == 0.75


def test_clip_score_clamps_to_zero_one_range():
    assert _parse_score_from_glm_response("1.0") == 1.0
    assert _parse_score_from_glm_response("0.0") == 0.0
    assert _parse_score_from_glm_response("not a score") == 0.0


def test_clip_score_returns_zero_on_glm_failure():
    with patch("layers.L3_visual.validators.call_glm4v", side_effect=RuntimeError("glm down")):
        assert clip_score("image.png", "coffee") == 0.0


def test_composite_score_weights_correctly(tmp_path):
    img = tmp_path / "candidate.png"
    ref = tmp_path / "ref.png"
    img.write_bytes(b"fake")
    ref.write_bytes(b"fake")

    with patch("layers.L3_visual.validators.call_glm4v", return_value="0.5"), patch(
        "integrations.llm_client.call_glm4v_multi", return_value="1.0"
    ):
        score = composite_score(img, "coffee", ref)

    assert score.prompt_score == 0.5
    assert score.face_score == 1.0
    assert score.composite_score == 0.7


def test_composite_score_falls_back_to_prompt_only_without_ref():
    with patch("layers.L3_visual.validators.call_glm4v", return_value="0.6"):
        score = composite_score("image.png", "coffee", None)

    assert score.prompt_score == 0.6
    assert score.face_score == 0.0
    assert score.composite_score == 0.6


def test_pick_best_returns_none_when_all_below_threshold():
    with patch("layers.L3_visual.validators.composite_score") as mock_score:
        mock_score.side_effect = [
            type("Score", (), {"composite_score": 0.1})(),
            type("Score", (), {"composite_score": 0.2})(),
        ]

        assert pick_best_candidate(["a.png", "b.png"], "coffee", min_acceptable_score=0.3) is None


def test_pick_best_selects_highest_composite():
    with patch("layers.L3_visual.validators.composite_score") as mock_score:
        low = type("Score", (), {"composite_score": 0.4})()
        high = type("Score", (), {"composite_score": 0.9})()
        mock_score.side_effect = [low, high]

        result = pick_best_candidate(["a.png", "b.png"], "coffee", min_acceptable_score=0.3)

    assert result is not None
    path, score = result
    assert path == "b.png"
    assert score.composite_score == 0.9
