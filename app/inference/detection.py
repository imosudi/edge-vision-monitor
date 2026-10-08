"""
Structured data classes and models for bounding boxes, detections, and inference performance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


@dataclass
class BoundingBox:
    """Normalised bounding box coordinates in [0.0, 1.0] range."""

    xmin: float
    ymin: float
    xmax: float
    ymax: float

    def __post_init__(self):
        # Clamp to [0.0, 1.0]
        self.xmin = max(0.0, min(1.0, float(self.xmin)))
        self.ymin = max(0.0, min(1.0, float(self.ymin)))
        self.xmax = max(0.0, min(1.0, float(self.xmax)))
        self.ymax = max(0.0, min(1.0, float(self.ymax)))

    def to_pixel_coords(self, width: int, height: int) -> tuple[int, int, int, int]:
        """Convert normalised coordinates to absolute integer pixel values (x1, y1, x2, y2)."""
        x1 = int(round(self.xmin * width))
        y1 = int(round(self.ymin * height))
        x2 = int(round(self.xmax * width))
        y2 = int(round(self.ymax * height))
        return max(0, min(width - 1, x1)), max(0, min(height - 1, y1)), max(0, min(width, x2)), max(0, min(height, y2))


@dataclass
class Detection:
    """An identified object instance within a video frame."""

    box: BoundingBox
    class_id: int
    class_name: str
    confidence: float

    def to_dict(self) -> dict:
        return {
            "class_id": self.class_id,
            "class_name": self.class_name,
            "confidence": round(self.confidence, 4),
            "box": {
                "xmin": round(self.box.xmin, 4),
                "ymin": round(self.box.ymin, 4),
                "xmax": round(self.box.xmax, 4),
                "ymax": round(self.box.ymax, 4),
            },
        }


@dataclass
class DetectionResult:
    """Complete inference and detection output for a single frame."""

    frame_seq: int
    source_id: str
    timestamp_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    monotonic_ts: float = 0.0
    detections: List[Detection] = field(default_factory=list)
    image_width: int = 640
    image_height: int = 480
    acquisition_ms: float = 0.0
    preprocessing_ms: float = 0.0
    hailo_exec_ms: float = 0.0
    postprocessing_ms: float = 0.0
    total_latency_ms: float = 0.0
    error_status: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "frame_seq": self.frame_seq,
            "source_id": self.source_id,
            "timestamp_utc": self.timestamp_utc,
            "monotonic_ts": round(self.monotonic_ts, 4),
            "detections": [d.to_dict() for d in self.detections],
            "detections_count": len(self.detections),
            "image_width": self.image_width,
            "image_height": self.image_height,
            "latency": {
                "acquisition_ms": round(self.acquisition_ms, 2),
                "preprocessing_ms": round(self.preprocessing_ms, 2),
                "hailo_exec_ms": round(self.hailo_exec_ms, 2),
                "postprocessing_ms": round(self.postprocessing_ms, 2),
                "total_latency_ms": round(self.total_latency_ms, 2),
            },
            "error_status": self.error_status,
        }
