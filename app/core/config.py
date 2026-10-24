"""
Application configuration management with Pydantic v2 and YAML support.
Supports environment variable overrides, schema validation, and safe public exposure.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Literal, Optional
import yaml
from pydantic import BaseModel, Field, field_validator


class ModelConfig(BaseModel):
    """Configuration for compiled Hailo/CPU YOLO11 model and post-processing."""

    hef_path: str = Field(default="models/model.hef", description="Path to compiled Hailo HEF model")
    onnx_path: Optional[str] = Field(default="models/onnx/model.onnx", description="Path to CPU ONNX model")
    active_backend: Literal["hailo", "cpu", "mock"] = Field(default="hailo", description="Initial inference backend ('hailo' or 'cpu')")
    labels_path: Optional[str] = Field(default="models/labels.txt", description="Path to class labels file")
    metadata_path: Optional[str] = Field(default=None, description="Optional path to model metadata YAML")
    input_width: Optional[int] = Field(default=None, description="Input width (auto-discovered from HEF/ONNX if None)")
    input_height: Optional[int] = Field(default=None, description="Input height (auto-discovered from HEF/ONNX if None)")
    confidence_threshold: float = Field(default=0.25, ge=0.0, le=1.0, description="Detection confidence threshold")
    nms_iou_threshold: float = Field(default=0.45, ge=0.0, le=1.0, description="Non-maximum suppression IoU threshold")
    max_detections: int = Field(default=100, ge=1, le=1000, description="Maximum detections per frame")


class VideoSourceConfig(BaseModel):
    """Configuration for video input sources."""

    default_source_type: Literal["picamera", "usb", "file"] = Field(
        default="file", description="Initial video input source"
    )
    picamera_camera_num: int = Field(default=0, ge=0, description="Picamera2 camera sensor index")
    usb_device_path: str = Field(default="/dev/video0", description="USB camera device path or index")
    video_file_path: Optional[str] = Field(default="media/sample.mp4", description="Prerecorded video file path")
    media_dir: str = Field(default="media", description="Restricted directory for prerecorded video files")
    capture_width: int = Field(default=640, ge=64, le=3840, description="Capture frame width")
    capture_height: int = Field(default=480, ge=64, le=2160, description="Capture frame height")
    capture_fps: int = Field(default=30, ge=1, le=120, description="Requested capture frame rate")
    loop_playback: bool = Field(default=True, description="Loop prerecorded video continuously")


class TelemetryThresholds(BaseModel):
    """Configurable thresholds for thermal and resource alarms."""

    warning_cpu_temp_c: float = Field(default=75.0, description="Warning threshold for CPU temperature in °C")
    critical_cpu_temp_c: float = Field(default=85.0, description="Critical threshold for CPU temperature in °C")
    warning_hailo_temp_c: float = Field(default=80.0, description="Warning threshold for Hailo NPU temperature in °C")
    critical_hailo_temp_c: float = Field(default=90.0, description="Critical threshold for Hailo NPU temperature in °C")
    warning_memory_percent: float = Field(default=85.0, description="Warning threshold for RAM usage %")
    critical_memory_percent: float = Field(default=95.0, description="Critical threshold for RAM usage %")
    warning_ambient_temp_c: float = Field(default=35.0, description="Warning threshold for ambient room temperature in °C")
    critical_ambient_temp_c: float = Field(default=45.0, description="Critical threshold for ambient room temperature in °C")
    warning_ambient_humidity_percent: float = Field(default=70.0, description="Warning threshold for ambient relative humidity %")
    critical_ambient_humidity_percent: float = Field(default=85.0, description="Critical threshold for ambient relative humidity %")
    warning_min_fps: Optional[float] = Field(default=None, ge=0.1, le=120.0, description="Warning threshold if inference FPS drops below this value")
    critical_min_fps: Optional[float] = Field(default=None, ge=0.1, le=120.0, description="Critical threshold if inference FPS drops below this value")


class TelemetryConfig(BaseModel):
    """Configuration for hardware and application telemetry sampling."""

    system_interval_seconds: float = Field(default=1.0, ge=0.1, le=60.0, description="System telemetry sampling interval")
    hailo_interval_seconds: float = Field(default=0.5, ge=0.05, le=60.0, description="Hailo NPU telemetry sampling interval")
    enable_hwmon: bool = Field(default=True, description="Enable Linux hwmon sensor collection")
    enable_thermal: bool = Field(default=True, description="Enable Linux thermal zone collection")
    enable_raspberry_pi: bool = Field(default=True, description="Enable Raspberry Pi sysfs and vcgencmd metrics")
    enable_hailo: bool = Field(default=True, description="Enable Hailo accelerator telemetry")
    enable_process: bool = Field(default=True, description="Enable process and cgroup resource monitoring")
    enable_ina219: bool = Field(default=False, description="Enable optional INA219 current/power sensor")
    ina219_i2c_bus: int = Field(default=1, ge=0, description="I2C bus number for INA219")
    ina219_i2c_address: int = Field(default=0x40, ge=0, description="I2C address for INA219")
    enable_ambient: bool = Field(default=True, description="Enable ESP32 ambient temperature and humidity sensor")
    ambient_serial_port: str = Field(default="/dev/ttyUSB0", description="Serial port device path for ESP32 ambient sensor")
    ambient_baud_rate: int = Field(default=115200, ge=1200, le=1000000, description="Serial baud rate for ESP32 ambient sensor")
    thresholds: TelemetryThresholds = Field(default_factory=TelemetryThresholds)


class StorageConfig(BaseModel):
    """Configuration for SQLite time-series telemetry and event storage."""

    db_path: str = Field(default="data/telemetry.db", description="Path to SQLite database file")
    retention_days: int = Field(default=7, ge=1, le=365, description="Database history retention in days")
    retention_hours: Optional[float] = Field(default=None, ge=0.1, description="Database history retention in hours (overrides retention_days if specified)")
    prune_interval_seconds: float = Field(default=3600.0, ge=1.0, le=86400.0, description="Interval in seconds between automated retention pruning runs")
    max_db_size_mb: Optional[float] = Field(default=500.0, ge=1.0, le=10000.0, description="Maximum database size in megabytes before size-based pruning is enforced")
    batch_size: int = Field(default=50, ge=1, le=1000, description="Max batch size before SQLite write transaction")
    flush_interval_seconds: float = Field(default=1.0, ge=0.1, le=10.0, description="Max delay before pending batch flush")
    max_queue_size: int = Field(default=5000, ge=100, le=50000, description="Maximum bounded queue size before shedding samples")


class ServerConfig(BaseModel):
    """Configuration for FastAPI and web preview server."""

    host: str = Field(default="127.0.0.1", description="Bind IP address (127.0.0.1 for least privilege)")
    port: int = Field(default=8000, ge=1024, le=65535, description="HTTP listening port")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO", description="Log level")
    preview_max_fps: int = Field(default=15, ge=1, le=60, description="Max MJPEG / WebSocket preview frame rate")
    preview_quality: int = Field(default=75, ge=10, le=100, description="JPEG quality for live preview stream")


class AppConfig(BaseModel):
    """Root configuration model combining all subsystems."""

    model: ModelConfig = Field(default_factory=ModelConfig)
    video: VideoSourceConfig = Field(default_factory=VideoSourceConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)

    def get_public_config(self) -> Dict[str, Any]:
        """Return safe, non-sensitive configuration summary for public API and dashboard."""
        return {
            "model": {
                "hef_path": self.model.hef_path,
                "labels_path": self.model.labels_path,
                "input_width": self.model.input_width,
                "input_height": self.model.input_height,
                "confidence_threshold": self.model.confidence_threshold,
                "nms_iou_threshold": self.model.nms_iou_threshold,
                "max_detections": self.model.max_detections,
            },
            "video": {
                "default_source_type": self.video.default_source_type,
                "capture_width": self.video.capture_width,
                "capture_height": self.video.capture_height,
                "capture_fps": self.video.capture_fps,
                "loop_playback": self.video.loop_playback,
            },
            "telemetry": {
                "system_interval_seconds": self.telemetry.system_interval_seconds,
                "hailo_interval_seconds": self.telemetry.hailo_interval_seconds,
                "enable_hwmon": self.telemetry.enable_hwmon,
                "enable_thermal": self.telemetry.enable_thermal,
                "enable_raspberry_pi": self.telemetry.enable_raspberry_pi,
                "enable_hailo": self.telemetry.enable_hailo,
                "enable_process": self.telemetry.enable_process,
                "enable_ina219": self.telemetry.enable_ina219,
                "enable_ambient": self.telemetry.enable_ambient,
                "ambient_serial_port": self.telemetry.ambient_serial_port,
                "thresholds": self.telemetry.thresholds.model_dump(),
            },
            "storage": {
                "retention_days": self.storage.retention_days,
                "retention_hours": self.storage.retention_hours or (self.storage.retention_days * 24.0),
                "prune_interval_seconds": self.storage.prune_interval_seconds,
                "max_db_size_mb": self.storage.max_db_size_mb,
                "batch_size": self.storage.batch_size,
                "flush_interval_seconds": self.storage.flush_interval_seconds,
            },
            "server": {
                "port": self.server.port,
                "preview_max_fps": self.server.preview_max_fps,
            },
        }


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """
    Load configuration from YAML file and apply environment variable overrides.
    Resolves configuration file in this order:
    1. Explicit config_path argument
    2. EVM_CONFIG_PATH environment variable
    3. 'config/config.yaml' if it exists
    4. Default AppConfig values
    """
    path_to_try = config_path or os.environ.get("EVM_CONFIG_PATH") or "config/config.yaml"
    raw_dict: Dict[str, Any] = {}

    if path_to_try and os.path.isfile(path_to_try):
        try:
            with open(path_to_try, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    raw_dict = loaded
        except Exception as e:
            raise ValueError(f"Failed to load configuration file at '{path_to_try}': {e}") from e

    # Apply environment variable overrides: EVM_SECTION__FIELD format
    # e.g. EVM_SERVER__PORT=8080, EVM_MODEL__HEF_PATH=/opt/model.hef
    for env_key, env_val in os.environ.items():
        if env_key.startswith("EVM_"):
            clean_key = env_key[4:].lower()
            if "__" in clean_key:
                section, key = clean_key.split("__", 1)
                if section not in raw_dict or not isinstance(raw_dict[section], dict):
                    raw_dict[section] = {}
                # Type cast boolean and numeric strings
                if env_val.lower() in ("true", "yes", "1"):
                    raw_dict[section][key] = True
                elif env_val.lower() in ("false", "no", "0"):
                    raw_dict[section][key] = False
                else:
                    try:
                        if "." in env_val:
                            raw_dict[section][key] = float(env_val)
                        else:
                            raw_dict[section][key] = int(env_val)
                    except ValueError:
                        raw_dict[section][key] = env_val

    return AppConfig.model_validate(raw_dict)
