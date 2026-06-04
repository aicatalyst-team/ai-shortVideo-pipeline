from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from layers.L2_creative.chains_v2 import lobster_creative_v2
from layers.L2_creative.schemas import SchemaValidationError, Storyboard
from layers.L2_creative.style_engine import get_template


def _valid_storyboard_json(main_char: str = "su_wan", reported_main: str | None = None) -> dict:
    return {
        "plan_id": "P_TEST",
        "title": "咖啡涨价",
        "theme": "咖啡涨价影响年轻人",
        "style_name": "hot_news_commentary",
        "main_character_id": reported_main or main_char,
        "total_duration_sec": 10,
        "shots": [
            {
                "scene_no": 1,
                "narration_segment": "你知道吗？2024 年咖啡价格暴涨 60%。",
                "estimated_duration_sec": 5,
                "character_id": main_char,
                "environment_id": "coffee_shop",
                "time_of_day": "morning",
                "subject_action": "looking at receipt",
                "subject_emotion": "surprised",
                "wardrobe_choice": "casual",
                "key_props": ["coffee cup", "receipt"],
                "camera_movement": "push_in",
                "lighting_mood": "warm",
                "composition": "rule_of_thirds",
            },
            {
                "scene_no": 2,
                "narration_segment": "原因是巴西霜冻和越南干旱同时发生。",
                "estimated_duration_sec": 5,
                "character_id": main_char,
                "environment_id": "coffee_shop",
                "time_of_day": "morning",
                "subject_action": "thinking deeply",
                "subject_emotion": "thinking",
                "wardrobe_choice": "casual",
                "key_props": ["coffee cup"],
                "camera_movement": "static",
                "lighting_mood": "warm",
                "composition": "center",
            },
        ],
    }


def _mock_deepseek_response(content: str):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    return resp


@pytest.mark.asyncio
async def test_creative_v2_returns_storyboard_on_valid_response():
    valid = _valid_storyboard_json()
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(return_value=_mock_deepseek_response(json.dumps(valid)))

    with patch("layers.L2_creative.chains_v2.get_deepseek", return_value=fake_client):
        result = await lobster_creative_v2("咖啡涨价", get_template("hot_news_commentary"))

    assert isinstance(result, Storyboard)
    assert result.title == "咖啡涨价"
    assert len(result.shots) == 2


@pytest.mark.asyncio
async def test_creative_v2_retries_on_schema_violation_then_succeeds():
    invalid = json.dumps({"plan_id": "P1"})
    valid = json.dumps(_valid_storyboard_json())
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        side_effect=[
            _mock_deepseek_response(invalid),
            _mock_deepseek_response(valid),
        ]
    )

    with patch("layers.L2_creative.chains_v2.get_deepseek", return_value=fake_client):
        result = await lobster_creative_v2("咖啡涨价", get_template("hot_news_commentary"), max_retries=1)

    assert isinstance(result, Storyboard)
    assert fake_client.chat.completions.create.await_count == 2


@pytest.mark.asyncio
async def test_creative_v2_raises_after_max_retries():
    invalid = json.dumps({"plan_id": "P1"})
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(return_value=_mock_deepseek_response(invalid))

    with patch("layers.L2_creative.chains_v2.get_deepseek", return_value=fake_client):
        with pytest.raises(SchemaValidationError) as exc_info:
            await lobster_creative_v2("咖啡涨价", get_template("hot_news_commentary"), max_retries=1)

    assert exc_info.value.attempts == 2
    assert fake_client.chat.completions.create.await_count == 2


@pytest.mark.asyncio
async def test_creative_v2_overrides_main_character_id():
    sneaky = _valid_storyboard_json(main_char="su_wan", reported_main="lin_yue")
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(return_value=_mock_deepseek_response(json.dumps(sneaky)))

    with patch("layers.L2_creative.chains_v2.get_deepseek", return_value=fake_client):
        result = await lobster_creative_v2(
            "咖啡涨价",
            get_template("hot_news_commentary"),
            main_character_id="su_wan",
        )

    assert result.main_character_id == "su_wan"


@pytest.mark.asyncio
async def test_creative_v2_passes_schema_in_system_prompt():
    valid = json.dumps(_valid_storyboard_json())
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(return_value=_mock_deepseek_response(valid))

    with patch("layers.L2_creative.chains_v2.get_deepseek", return_value=fake_client):
        await lobster_creative_v2("咖啡涨价", get_template("hot_news_commentary"))

    messages = fake_client.chat.completions.create.await_args.kwargs["messages"]
    system_content = messages[0]["content"]
    assert "Storyboard" in system_content or "shots" in system_content
    assert "character_id" in system_content
    assert "environment_id" in system_content


@pytest.mark.asyncio
async def test_creative_v2_retry_message_includes_error_detail():
    invalid = json.dumps({"plan_id": "P1"})
    valid = json.dumps(_valid_storyboard_json())
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        side_effect=[
            _mock_deepseek_response(invalid),
            _mock_deepseek_response(valid),
        ]
    )

    with patch("layers.L2_creative.chains_v2.get_deepseek", return_value=fake_client):
        await lobster_creative_v2("咖啡涨价", get_template("hot_news_commentary"), max_retries=1)

    second_call = fake_client.chat.completions.create.await_args_list[1]
    second_messages = second_call.kwargs["messages"]
    last_msg = second_messages[-1]["content"]
    assert "schema" in last_msg.lower() or "违反" in last_msg
    assert "Field required" in last_msg or "field required" in last_msg.lower()
