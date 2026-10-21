"""
Pydantic v2 schemas for API requests, responses, and validation contracts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from app import __version__


class HealthResponse(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    uptime_seconds: float
    telemetry_active: bool
    inference_active: bool
    version: str = __version__


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
    source_type: Literal["picamera", "usb", "file", "browser"]
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


class WorkloadStartRequest(BaseModel):
    workload_type: Literal["A", "B", "C", "D", "a", "b", "c", "d"]
    duration_seconds: Optional[float] = Field(default=60.0, ge=5.0, le=3600.0)
    target_temp_c: Optional[float] = Field(default=100.0, ge=50.0, le=102.0)
    safety_temp_limit_c: Optional[float] = Field(default=102.0, ge=60.0, le=102.0)
    simulate: Optional[bool] = False
    stream_count: Optional[int] = Field(default=4, ge=1, le=16)
    buffer_size: Optional[int] = Field(default=120, ge=10, le=500)
    media_file: Optional[str] = None


class WorkloadStatusResponse(BaseModel):
    active: bool
    state: str
    workload_type: Optional[str] = None
    workload_name: Optional[str] = None
    workload_title: Optional[str] = None
    elapsed_seconds: float = 0.0
    duration_seconds: float = 60.0
    progress_percent: float = 0.0
    target_temp_c: Optional[float] = None
    safety_temp_limit_c: Optional[float] = None
    current_tj_c: Optional[float] = None
    peak_tj_c: Optional[float] = None
    ts0_c: Optional[float] = None
    ts1_c: Optional[float] = None
    clock_frequency_mhz: Optional[float] = None
    initial_clock_mhz: Optional[float] = None
    min_clock_mhz: Optional[float] = None
    throttling_level: Optional[int] = None
    throttling_active: bool = False
    throttling_observed: bool = False
    hysteresis_recovered: bool = False
    current_fps: float = 0.0
    mean_fps: float = 0.0
    samples_count: int = 0
    abort_reason: Optional[str] = None
    session_id: Optional[str] = None
    session_summary: Optional[Dict[str, Any]] = None


class WorkloadStopResponse(BaseModel):
    stopped: bool
    message: str
    session_id: Optional[str] = None
    summary: Optional[Dict[str, Any]] = None

