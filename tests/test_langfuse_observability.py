from __future__ import annotations

import contextvars
import sys
import types

import pytest

from core import langfuse_client
from core.langfuse_client import observe
from core.trace_context import (
    get_current_trace_id,
    get_or_generate_trace_id,
    reset_current_trace_id,
    set_current_trace_id,
)


def _reset_langfuse_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(langfuse_client, "_client", None)
    monkeypatch.setattr(langfuse_client, "_initialized", False)


def test_trace_context_set_get_reset() -> None:
    token = set_current_trace_id("trace-123")
    try:
        assert get_current_trace_id() == "trace-123"
    finally:
        reset_current_trace_id(token)
    assert get_current_trace_id() is None


def test_get_or_generate_trace_id_creates_16_chars_when_missing() -> None:
    token = set_current_trace_id(None)
    try:
        trace_id = get_or_generate_trace_id()
        assert len(trace_id) == 16
        assert get_current_trace_id() == trace_id
    finally:
        reset_current_trace_id(token)


def test_observe_sync_passthrough_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(langfuse_client, "get_langfuse_client", lambda: None)

    @observe(name="sync_test")
    def fn(x: int) -> int:
        return x + 1

    assert fn(2) == 3


@pytest.mark.asyncio
async def test_observe_async_passthrough_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(langfuse_client, "get_langfuse_client", lambda: None)

    @observe(name="async_test")
    async def fn(x: int) -> int:
        return x + 1

    assert await fn(4) == 5


def test_observe_preserves_return_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(langfuse_client, "get_langfuse_client", lambda: None)

    @observe(name="return_test")
    def fn() -> dict[str, str]:
        return {"ok": "yes"}

    assert fn() == {"ok": "yes"}


def test_observe_falls_back_when_langfuse_import_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(langfuse_client, "get_langfuse_client", lambda: object())
    monkeypatch.setitem(sys.modules, "langfuse.decorators", None)

    @observe(name="fallback_test")
    def fn() -> str:
        return "business-ok"

    assert fn() == "business-ok"


def test_observe_does_not_rerun_original_when_business_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(langfuse_client, "get_langfuse_client", lambda: object())
    calls = {"count": 0}

    @observe(name="exception_test")
    def fn() -> None:
        calls["count"] += 1
        raise RuntimeError("business failed")

    with pytest.raises(RuntimeError, match="business failed"):
        fn()
    assert calls["count"] == 1


def test_get_langfuse_client_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_langfuse_singleton(monkeypatch)
    monkeypatch.setattr(langfuse_client, "_is_enabled", lambda: True)

    class DummySettings:
        langfuse_public_key = "pk"
        langfuse_secret_key = "sk"
        langfuse_host = "https://cloud.langfuse.com"

    class DummyLangfuse:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def flush(self) -> None:
            pass

    fake_module = types.ModuleType("langfuse")
    fake_module.Langfuse = DummyLangfuse
    monkeypatch.setitem(sys.modules, "langfuse", fake_module)
    monkeypatch.setattr(langfuse_client, "get_settings", lambda: DummySettings())

    first = langfuse_client.get_langfuse_client()
    second = langfuse_client.get_langfuse_client()

    assert first is second
    assert first.kwargs["public_key"] == "pk"


def test_langfuse_disabled_returns_none_even_with_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_langfuse_singleton(monkeypatch)

    class DummySettings:
        langfuse_enabled = False
        langfuse_public_key = "pk"
        langfuse_secret_key = "sk"

    monkeypatch.setattr(langfuse_client, "get_settings", lambda: DummySettings())

    assert langfuse_client.get_langfuse_client() is None
