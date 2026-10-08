"""
Structured logging configuration with rate-limiting for hardware telemetry errors.
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone
from typing import Dict, Optional


class StructuredFormatter(logging.Formatter):
    """Formats log records with ISO-8601 UTC timestamps, component names, and structured fields."""

    def format(self, record: logging.LogRecord) -> str:
        utc_dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        iso_time = utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        component = getattr(record, "component", record.name)
        event_type = getattr(record, "event_type", "GENERAL")
        extra_info = getattr(record, "extra_info", None)

        msg = f"[{iso_time}] [{record.levelname:7s}] [{component}] [{event_type}] {record.getMessage()}"
        if extra_info:
            msg += f" | {extra_info}"
        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)
        return msg


class RateLimitedLogger:
    """
    Wraps a logger to throttle repetitive errors (e.g., from polling unreadable sysfs sensors).
    Only logs identical message keys once per window_seconds.
    """

    def __init__(self, logger: logging.Logger, window_seconds: float = 30.0):
        self._logger = logger
        self._window_seconds = window_seconds
        self._last_logged: Dict[str, float] = {}

    def log_throttled(
        self,
        level: int,
        key: str,
        msg: str,
        component: str = "TELEMETRY",
        event_type: str = "ERROR",
        *args,
        **kwargs,
    ) -> bool:
        now = time.monotonic()
        last = self._last_logged.get(key, 0.0)
        if now - last >= self._window_seconds:
            self._last_logged[key] = now
            extra = kwargs.pop("extra", {})
            extra.update({"component": component, "event_type": event_type})
            self._logger.log(level, msg, *args, extra=extra, **kwargs)
            return True
        return False


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Configure root logger with structured formatter and stream handler."""
    root_logger = logging.getLogger("evm")
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger.setLevel(numeric_level)

    # Avoid duplicate handlers if called multiple times
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredFormatter())
        root_logger.addHandler(handler)

    # Keep third-party loggers sane
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(numeric_level)

    return root_logger


def get_logger(component_name: str) -> logging.Logger:
    """Get a named logger child under the 'evm' hierarchy."""
    return logging.getLogger(f"evm.{component_name}")
