from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from layers.L2_creative.chains_v2 import lobster_evaluate_v2
from layers.L2_creative.schemas import SchemaValidationError, ScoreReport, Storyboard


def _storyboard() -> Storyboard:
    return Storyboard(
        plan_id="P_TEST",
        title="咖啡涨价",
        theme="咖啡涨价影响年轻人",
        style_name="hot_news_commentary",
        main_character_id="su_wan",
        total_duration_sec=10,
        shots=[
            {
                "scene_no": 1,
                "narration_segment": "你知道吗？2024 年咖啡价格暴涨 60%。",
                "estimated_duration_sec": 5,
                "character_id": "su_wan",
                "environment_id": "coffee_shop",
                "time_of_day": "morning",
                "subject_action": "looking at receipt",
                "subject_emotion": "surprised",
                "key_props": ["coffee cup", "receipt"],
                "camera_movement": "push_in",
                "lighting_mood": "warm",
                "composition": "rule_of_thirds",
            },
            {
                "scene_no": 2,
                "narration_segment": "原因是巴西霜冻和越南干旱同时发生。",
                "estimated_duration_sec": 5,
                "character_id": "su_wan",
                "environment_id": "coffee_shop",
                "time_of_day": "morning",
                "subject_action": "thinking deeply",
                "subject_emotion": "thinking",
                "key_props": ["coffee cup"],
                "camera_movement": "static",
                "lighting_mood": "warm",
                "composition": "center",
            },
        ],
    )


def _score_report(plan_id: str = "P_TEST") -> dict:
    return {
        "storyboard_plan_id": plan_id,
        "overall_score": 82.5,
        "dimension_scores": [
            {"dimension": "hook", "score": 86, "reason": "开头有数字冲击。"},
            {"dimension": "narrative", "score": 80, "reason": "原因链条清晰。"},
            {"dimension": "visual", "score": 78, "reason": "画面和旁白基本一致。"},
            {"dimension": "rhythm", "score": 84, "reason": "两段节奏紧凑。"},
            {"dimension": "potential", "score": 85, "reason": "有讨论价值。"},
        ],
        "strengths": ["数字开场明确", "视觉实体清晰"],
        "improvements": ["可增加结尾评论钩子"],
        "verdict": "pass",
    }


def _mock_glm_response(content: str):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    return resp


def _mock_glm_client(*contents: str):
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = [_mock_glm_response(content) for content in contents]
    return fake_client


@pytest.mark.asyncio
async def test_evaluate_v2_returns_score_report_on_valid_response():
    fake_client = _mock_glm_client(json.dumps(_score_report()))

    with patch("layers.L2_creative.chains_v2.get_glm", return_value=fake_client):
        result = await lobster_evaluate_v2(_storyboard())

    assert isinstance(result, ScoreReport)
    assert result.overall_score == 82.5
    assert result.verdict == "pass"


@pytest.mark.asyncio
async def test_evaluate_v2_retries_on_schema_violation():
    invalid = json.dumps({"storyboard_plan_id": "P_TEST"})
    valid = json.dumps(_score_report())
    fake_client = _mock_glm_client(invalid, valid)

    with patch("layers.L2_creative.chains_v2.get_glm", return_value=fake_client):
        result = await lobster_evaluate_v2(_storyboard(), max_retries=1)

    assert isinstance(result, ScoreReport)
    assert fake_client.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_evaluate_v2_raises_after_max_retries():
    invalid = json.dumps({"storyboard_plan_id": "P_TEST"})
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _mock_glm_response(invalid)

    with patch("layers.L2_creative.chains_v2.get_glm", return_value=fake_client):
        with pytest.raises(SchemaValidationError) as exc_info:
            await lobster_evaluate_v2(_storyboard(), max_retries=1)

    assert exc_info.value.attempts == 2
    assert fake_client.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_evaluate_v2_overrides_storyboard_plan_id():
    fake_client = _mock_glm_client(json.dumps(_score_report(plan_id="WRONG_PLAN")))

    with patch("layers.L2_creative.chains_v2.get_glm", return_value=fake_client):
        result = await lobster_evaluate_v2(_storyboard())

    assert result.storyboard_plan_id == "P_TEST"
