"""request trace_id contextvars for Langfuse observation.

HTTP middleware writes X-Trace-Id into this context, then observed business
functions can reuse the same value as Langfuse session_id.
"""
from __future__ import annotations

import contextvars
import uuid
from typing import Optional

_current_trace_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_trace_id", default=None
)


def set_current_trace_id(trace_id: str | None) -> contextvars.Token:
    """Set the current request trace_id and return a token for reset."""
    return _current_trace_id.set(trace_id)


def reset_current_trace_id(token: contextvars.Token) -> None:
    """Reset the contextvar to its previous value."""
    _current_trace_id.reset(token)


def get_current_trace_id() -> str | None:
    """Return current trace_id, or None for CLI/background contexts."""
    return _current_trace_id.get()


def get_or_generate_trace_id() -> str:
    """Return current trace_id, generating one if no request context exists."""
    trace_id = _current_trace_id.get()
    if trace_id:
        return trace_id
    new_trace_id = uuid.uuid4().hex[:16]
    _current_trace_id.set(new_trace_id)
    return new_trace_id
