"""
Pydantic v2 schemas for API requests, responses, and validation contracts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    uptime_seconds: float
    telemetry_active: bool
    inference_active: bool
    version: str = "1.0.0"


class ReadinessResponse(BaseModel):
    ready: bool
    active_backend: str = "hailo"
    hailo_ready: bool
    model_status: str
    model_path: str = ""
    hef_path: str = ""
    error_message: Optional[str] = None
    is_mock: bool = False


class StatusResponse(BaseModel):
    application_state: str
    active_source: str
    active_source_type: str
    active_backend: str = "hailo"
    inference_running: bool
    current_fps: float
    alarms_count: int
    queue_depth: int = 0


class BackendSelectionRequest(BaseModel):
    backend: Literal["hailo", "cpu", "mock"]
    model_path: Optional[str] = None


class BackendDetail(BaseModel):
    name: str
    available: bool
    model_path: Optional[str] = None
    device_node: Optional[str] = None
    runtime_installed: bool = False


class BackendsResponse(BaseModel):
    current_backend: str
    backends: Dict[str, BackendDetail]


class SourceSelectionRequest(BaseModel):
    source_type: Literal["picamera", "usb", "file"]
    device: Optional[str] = None
    camera_num: Optional[int] = None
    file_path: Optional[str] = None
    width: Optional[int] = Field(default=640, ge=64, le=3840)
    height: Optional[int] = Field(default=480, ge=64, le=2160)
    fps: Optional[int] = Field(default=30, ge=1, le=120)
    loop: Optional[bool] = True


class PlaybackControlRequest(BaseModel):
    action: Literal["play", "pause", "restart"]


class BoundingBoxSchema(BaseModel):
    xmin: float
    ymin: float
    xmax: float
    ymax: float


class DetectionItemSchema(BaseModel):
    class_id: int
    class_name: str
    confidence: float
    box: BoundingBoxSchema


class LatestDetectionsResponse(BaseModel):
    count: int
    detections: List[DetectionItemSchema]
    timestamp_utc: Optional[str] = None
    image_width: int = 640
    image_height: int = 480


class SystemInfoResponse(BaseModel):
    hostname: str
    platform: str
    os_kernel: str
    python_version: str
    cpu_model: str
    hailo_device_present: bool
    hailo_runtime_installed: bool
