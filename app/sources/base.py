"""
Abstract base class and data structures for video input sources.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import numpy as np


@dataclass
class VideoFrame:
    """A single captured video frame with capture metadata."""

    frame_seq: int
    data: np.ndarray
    source_id: str
    width: int
    height: int
    timestamp_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    monotonic_ts: float = 0.0


class BaseVideoSource(ABC):
    """Abstract interface for video capture sources."""

    @abstractmethod
    def start(self) -> bool:
        """Initialise hardware/file and begin frame capture."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Release camera handle or file and stop worker."""
        pass

    @abstractmethod
    def get_frame(self, timeout: float = 0.5) -> Optional[VideoFrame]:
        """Retrieve freshest frame with bounded timeout."""
        pass

    @abstractmethod
    def is_active(self) -> bool:
        """Check if source is actively capturing."""
        pass

    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        """Return source configuration, connection state, and dropped frame counts."""
        pass
