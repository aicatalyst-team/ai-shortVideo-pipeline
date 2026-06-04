from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from core.logging_setup import (
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
    TraceIdFilter,
    setup_logging,
)
from core.trace_context import reset_current_trace_id, set_current_trace_id


def test_setup_logging_creates_log_dir(tmp_path):
    log_dir = tmp_path / "logs"

    setup_logging("testproc", log_dir=str(log_dir))

    assert log_dir.exists()


def test_setup_logging_installs_stream_and_rotating_file_handlers(tmp_path):
    setup_logging("testproc", log_dir=str(tmp_path))

    handlers = logging.getLogger().handlers
    assert sum(isinstance(h, logging.StreamHandler) for h in handlers) >= 1
    assert sum(isinstance(h, RotatingFileHandler) for h in handlers) == 1


def test_setup_logging_is_idempotent(tmp_path):
    setup_logging("testproc", log_dir=str(tmp_path))
    setup_logging("testproc", log_dir=str(tmp_path))

    handlers = logging.getLogger().handlers
    assert len(handlers) == 2
    assert sum(isinstance(h, RotatingFileHandler) for h in handlers) == 1


def test_trace_id_filter_injects_current_trace_id():
    token = set_current_trace_id("trace_123")
    try:
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", (), None)
        assert TraceIdFilter().filter(record) is True
        assert record.trace_id == "trace_123"
    finally:
        reset_current_trace_id(token)


def test_trace_id_filter_defaults_to_dash():
    token = set_current_trace_id(None)
    try:
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", (), None)

        assert TraceIdFilter().filter(record) is True
        assert record.trace_id == "-"
    finally:
        reset_current_trace_id(token)


def test_setup_logging_noisy_loggers_set_to_warning(tmp_path):
    setup_logging("testproc", log_dir=str(tmp_path))

    assert logging.getLogger("uvicorn.access").level == logging.WARNING


def test_setup_logging_writes_to_file(tmp_path):
    setup_logging("testproc", log_dir=str(tmp_path))
    logging.getLogger("tests.logging").info("needle-log-line")

    for handler in logging.getLogger().handlers:
        handler.flush()

    log_file = tmp_path / "testproc.log"
    assert log_file.exists()
    assert "needle-log-line" in log_file.read_text(encoding="utf-8")


def test_rotating_file_handler_uses_expected_limits(tmp_path):
    setup_logging("testproc", log_dir=str(tmp_path))

    file_handler = next(
        h for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler)
    )
    assert file_handler.maxBytes == LOG_MAX_BYTES
    assert file_handler.backupCount == LOG_BACKUP_COUNT
