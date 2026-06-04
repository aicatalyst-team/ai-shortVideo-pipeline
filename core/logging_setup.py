"""D41-D unified logging setup.

Each process entrypoint should call setup_logging() once at startup. It keeps
stdout logs for docker compose logs and writes rotating archives under
/app/data/logs so container recreates do not erase incident history.
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

LOG_FORMAT = "%(asctime)s [%(levelname)s] [trace=%(trace_id)s] %(name)s: %(message)s"
LOG_DIR_DEFAULT = "/app/data/logs"
LOG_MAX_BYTES = 50 * 1024 * 1024
LOG_BACKUP_COUNT = 10


class TraceIdFilter(logging.Filter):
    """Inject current trace_id from contextvars into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            from core.trace_context import get_current_trace_id

            trace_id = get_current_trace_id() or "-"
        except Exception:
            trace_id = "-"
        record.trace_id = trace_id
        return True


def setup_logging(
    process_name: str,
    level: int | str = "INFO",
    log_dir: str | None = None,
) -> None:
    """Idempotently configure root logging for stdout + rotating file output."""
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

    resolved_level = logging.getLevelName(level) if isinstance(level, str) else level
    if isinstance(resolved_level, str):
        resolved_level = logging.INFO

    log_dir = log_dir or os.environ.get("APP_LOG_DIR") or LOG_DIR_DEFAULT
    os.makedirs(log_dir, exist_ok=True)

    trace_filter = TraceIdFilter()
    formatter = logging.Formatter(LOG_FORMAT)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(resolved_level)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(trace_filter)

    file_handler = RotatingFileHandler(
        os.path.join(log_dir, f"{process_name}.log"),
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(resolved_level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(trace_filter)

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    root.setLevel(resolved_level)
    root.addHandler(stream_handler)
    root.addHandler(file_handler)

    for noisy in ("uvicorn.access", "httpx", "httpcore", "asyncio", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
