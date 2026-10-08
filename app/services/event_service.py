"""
System and hardware event publication and recording.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional
from app.core.logging_config import get_logger
from app.storage.models import SystemEventRecord
from app.storage.repository import TelemetryRepository

logger = get_logger("SERVICE.EVENT")


class EventService:
    """Publishes and persists operational, lifecycle, and hardware warning events."""

    def __init__(self, repository: TelemetryRepository):
        self._repository = repository
        self._listeners: List[Callable[[SystemEventRecord], None]] = []

    def subscribe(self, callback: Callable[[SystemEventRecord], None]) -> None:
        """Register a callback for real-time event notifications."""
        self._listeners.append(callback)

    def unsubscribe(self, callback: Callable[[SystemEventRecord], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def emit(
        self,
        event_type: str,
        message: str,
        severity: str = "INFO",
        component: str = "SYSTEM",
        details: Optional[Dict[str, Any]] = None,
    ) -> SystemEventRecord:
        """Create and publish a system event."""
        details_str = json.dumps(details) if details else None
        event = SystemEventRecord(
            event_type=event_type,
            severity=severity,
            component=component,
            message=message,
            details_json=details_str,
        )

        # Persist asynchronously
        self._repository.enqueue_event(event)

        # Notify active listeners (e.g. WebSocket clients)
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception as e:
                logger.warning("Error notifying event listener: %s", e)

        log_fn = getattr(logger, severity.lower(), logger.info)
        log_fn("[%s] %s: %s", component, event_type, message)
        return event
