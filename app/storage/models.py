"""
Data models for persistent SQLite storage and time-series records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class TelemetrySample:
    """A single hardware or system telemetry measurement."""

    metric_name: str
    value: Optional[float]
    unit: str
    source: str
    availability_status: str  # AVAILABLE, UNAVAILABLE, UNSUPPORTED, PERMISSION_DENIED, STALE, READ_ERROR
    timestamp_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    monotonic_ts: float = 0.0
    error_message: Optional[str] = None
    id: Optional[int] = None


@dataclass
class InferenceFrameRecord:
    """Summary record for a single evaluated video frame."""

    frame_seq: int
    source_id: str
    timestamp_utc: str
    acquisition_ms: float
    preprocessing_ms: float
    hailo_exec_ms: float
    postprocessing_ms: float
    total_latency_ms: float
    detections_count: int
    dropped: bool = False
    error_status: Optional[str] = None
    id: Optional[int] = None


@dataclass
class DetectionRecord:
    """Individual object detection bounding box and class attribution."""

    frame_seq: int
    timestamp_utc: str
    class_id: int
    class_name: str
    confidence: float
    box_xmin: float  # Normalised 0.0 to 1.0
    box_ymin: float
    box_xmax: float
    box_ymax: float
    id: Optional[int] = None


@dataclass
class SystemEventRecord:
    """Lifecycle, hardware state change, or diagnostic event."""

    event_type: str
    severity: str  # INFO, WARNING, ERROR, CRITICAL
    component: str
    message: str
    timestamp_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    details_json: Optional[str] = None
    id: Optional[int] = None
