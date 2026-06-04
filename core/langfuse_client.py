"""Langfuse client singleton and safe observe decorator.

Langfuse is optional. When disabled or misconfigured, observation becomes a
no-op and business code keeps running normally.
"""
from __future__ import annotations

import asyncio
import functools
import logging
from typing import Callable

from config.settings import get_settings

log = logging.getLogger(__name__)

_client = None
_initialized = False


def _is_enabled() -> bool:
    cfg = get_settings()
    return bool(cfg.langfuse_enabled and cfg.langfuse_public_key and cfg.langfuse_secret_key)


def get_langfuse_client():
    """Return process-wide Langfuse client, or None when disabled."""
    global _client, _initialized
    if _initialized:
        return _client

    _initialized = True
    if not _is_enabled():
        log.info("[langfuse] disabled or missing keys; observe is no-op")
        _client = None
        return None

    try:
        from langfuse import Langfuse

        cfg = get_settings()
        _client = Langfuse(
            public_key=cfg.langfuse_public_key,
            secret_key=cfg.langfuse_secret_key,
            host=cfg.langfuse_host,
        )
        log.info("[langfuse] initialized host=%s", cfg.langfuse_host)
    except Exception as exc:
        log.warning("[langfuse] init failed; observe is no-op: %s", exc)
        _client = None
    return _client


def observe(*, name: str | None = None, as_type: str = "generation"):
    """Safe wrapper around langfuse.decorators.observe.

    Supports sync and async functions. Langfuse failures are swallowed and the
    original function is still executed.
    """

    def decorator(func: Callable) -> Callable:
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                client = get_langfuse_client()
                if client is None:
                    return await func(*args, **kwargs)
                try:
                    from langfuse.decorators import langfuse_context, observe as lf_observe
                    from core.trace_context import get_or_generate_trace_id

                    trace_id = get_or_generate_trace_id()
                    lf_as_type = "generation" if as_type == "generation" else None

                    @lf_observe(name=name or func.__name__, as_type=lf_as_type)
                    async def observed_call():
                        langfuse_context.update_current_trace(session_id=trace_id)
                        return await func(*args, **kwargs)
                except Exception as exc:
                    log.warning("[langfuse] observe failed name=%s: %s", name or func.__name__, exc)
                    return await func(*args, **kwargs)
                return await observed_call()

            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            client = get_langfuse_client()
            if client is None:
                return func(*args, **kwargs)
            try:
                from langfuse.decorators import langfuse_context, observe as lf_observe
                from core.trace_context import get_or_generate_trace_id

                trace_id = get_or_generate_trace_id()
                lf_as_type = "generation" if as_type == "generation" else None

                @lf_observe(name=name or func.__name__, as_type=lf_as_type)
                def observed_call():
                    langfuse_context.update_current_trace(session_id=trace_id)
                    return func(*args, **kwargs)
            except Exception as exc:
                log.warning("[langfuse] observe failed name=%s: %s", name or func.__name__, exc)
                return func(*args, **kwargs)
            return observed_call()

        return sync_wrapper

    return decorator


def flush() -> None:
    """Flush buffered Langfuse events, if enabled."""
    client = get_langfuse_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception as exc:
        log.warning("[langfuse] flush failed: %s", exc)
