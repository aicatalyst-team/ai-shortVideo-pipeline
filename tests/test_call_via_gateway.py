from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_call_via_gateway_success():
    from integrations.llm_client import call_via_gateway

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "content": "hello",
        "provider": "deepseek",
        "model": "deepseek-chat",
        "input_tokens": 10,
        "output_tokens": 20,
        "cost_cny": 0.001,
        "latency_ms": 50,
        "fallback_chain": [{"provider": "deepseek", "status": "success"}],
        "trace_id": "trace-1",
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await call_via_gateway("you are a bot", "hello")
        assert result == "hello"


@pytest.mark.asyncio
async def test_call_via_gateway_503_raises():
    from integrations.llm_client import call_via_gateway

    mock_response = MagicMock()
    mock_response.status_code = 503
    mock_response.json.return_value = {
        "error": "all_providers_failed",
        "message": "exhausted",
        "fallback_chain": [{"provider": "deepseek", "status": "5xx"}],
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(RuntimeError):
            await call_via_gateway("you are a bot", "hello")
