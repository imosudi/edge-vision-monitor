"""
Shared-memory (/dev/shm) Inter-Process Communication (IPC) coordination layer.
Enables high-performance, non-blocking zero-copy state sharing and control
between decomposed least-privilege microservices (ingress, inference, telemetry, gateway).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging_config import get_logger

logger = get_logger("CORE.IPC")

# Default shared memory root (POSIX tmpfs in RAM)
SHM_DIR = Path("/dev/shm")

# State & metadata files
TELEMETRY_METRICS_FILE = SHM_DIR / "evm_telemetry_latest.json"
TELEMETRY_CATALOG_FILE = SHM_DIR / "evm_telemetry_catalog.json"
TELEMETRY_STATUS_FILE = SHM_DIR / "evm_telemetry_status.json"

INFERENCE_LATEST_FILE = SHM_DIR / "evm_inference_latest.json"
ENGINE_STATUS_FILE = SHM_DIR / "evm_engine_status.json"
PREVIEW_JPEG_FILE = SHM_DIR / "evm_latest_preview.jpg"

SOURCE_STATUS_FILE = SHM_DIR / "evm_source_status.json"
SOURCE_CATALOG_FILE = SHM_DIR / "evm_source_catalog.json"
SOURCE_COMMAND_FILE = SHM_DIR / "evm_source_command.json"

RAW_FRAME_BIN_FILE = SHM_DIR / "evm_raw_frame.bin"
RAW_FRAME_META_FILE = SHM_DIR / "evm_raw_frame.json"


def _atomic_write_json(target_path: Path, data: Any) -> None:
    """Atomically write JSON data using a temporary file and POSIX rename."""
    try:
        if not target_path.parent.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target_path.with_suffix(f".tmp_{os.getpid()}")
        content = json.dumps(data)
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(target_path)
    except Exception as exc:
        logger.debug("Failed atomic JSON write to %s: %s", target_path, exc)


def _atomic_write_bytes(target_path: Path, data: bytes) -> None:
    """Atomically write binary data using a temporary file and POSIX rename."""
    try:
        if not target_path.parent.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target_path.with_suffix(f".tmp_{os.getpid()}")
        tmp_path.write_bytes(data)
        tmp_path.replace(target_path)
    except Exception as exc:
        logger.debug("Failed atomic binary write to %s: %s", target_path, exc)


def _read_json(target_path: Path, default: Any = None) -> Any:
    """Read and deserialize JSON file safely with fallback."""
    if not target_path.exists():
        return default
    try:
        content = target_path.read_text(encoding="utf-8")
        if not content:
            return default
        return json.loads(content)
    except Exception:
        return default


def _read_bytes(target_path: Path) -> Optional[bytes]:
    """Read raw binary bytes safely with fallback."""
    if not target_path.exists():
        return None
    try:
        return target_path.read_bytes()
    except Exception:
        return None


# -----------------------------------------------------------------------------
# 1. Telemetry Publishing & Consumption
# -----------------------------------------------------------------------------

def publish_telemetry_snapshot(
    metrics: Dict[str, Any],
    catalog: Optional[List[Dict[str, Any]]] = None,
    alarms: Optional[Dict[str, str]] = None,
    status: Optional[Dict[str, Any]] = None,
) -> None:
    """Publish the latest hardware and system telemetry snapshot to /dev/shm."""
    payload = {
        "timestamp_utc": time.time(),
        "metrics": metrics,
        "alarms": alarms or {},
        "active_alarms_count": len(alarms) if alarms else 0,
    }
    _atomic_write_json(TELEMETRY_METRICS_FILE, payload)

    if catalog is not None:
        _atomic_write_json(TELEMETRY_CATALOG_FILE, catalog)

    if status is not None:
        _atomic_write_json(TELEMETRY_STATUS_FILE, status)


def get_ipc_telemetry_metrics() -> Dict[str, Any]:
    """Read the latest telemetry metrics snapshot from /dev/shm."""
    data = _read_json(TELEMETRY_METRICS_FILE, default={})
    return data.get("metrics", {})


def get_ipc_telemetry_catalog() -> List[Dict[str, Any]]:
    """Read the discovered telemetry catalogue from /dev/shm."""
    return _read_json(TELEMETRY_CATALOG_FILE, default=[])


def get_ipc_telemetry_status() -> Dict[str, Any]:
    """Read telemetry service status and alarms from /dev/shm."""
    return _read_json(TELEMETRY_STATUS_FILE, default={"active": False, "active_alarms_count": 0})


# -----------------------------------------------------------------------------
# 2. Inference Publishing & Consumption
# -----------------------------------------------------------------------------

def publish_inference_frame(
    jpeg_bytes: Optional[bytes],
    detections: List[Dict[str, Any]],
    stats: Dict[str, Any],
    frame_seq: int = 0,
    timestamp_utc: Optional[str] = None,
    image_width: int = 640,
    image_height: int = 480,
) -> None:
    """Publish latest annotated JPEG preview, bounding boxes, and performance stats."""
    if jpeg_bytes:
        _atomic_write_bytes(PREVIEW_JPEG_FILE, jpeg_bytes)

    inference_payload = {
        "frame_seq": frame_seq,
        "timestamp_utc": timestamp_utc,
        "image_width": image_width,
        "image_height": image_height,
        "detections": detections,
        "count": len(detections),
        "stats": stats,
    }
    _atomic_write_json(INFERENCE_LATEST_FILE, inference_payload)


def publish_engine_status(status_dict: Dict[str, Any]) -> None:
    """Publish inference engine hardware readiness and backend metadata."""
    _atomic_write_json(ENGINE_STATUS_FILE, status_dict)


def get_ipc_latest_jpeg() -> Optional[bytes]:
    """Read latest annotated JPEG bytes from /dev/shm for live MJPEG streaming."""
    return _read_bytes(PREVIEW_JPEG_FILE)


def get_ipc_latest_detections() -> Dict[str, Any]:
    """Read latest detections list and image dimensions from /dev/shm."""
    return _read_json(
        INFERENCE_LATEST_FILE,
        default={"count": 0, "detections": [], "image_width": 640, "image_height": 480},
    )


def get_ipc_inference_stats() -> Dict[str, Any]:
    """Read rolling inference latencies, FPS, and backend status from /dev/shm."""
    data = _read_json(INFERENCE_LATEST_FILE, default={})
    return data.get("stats", {})


def get_ipc_engine_status() -> Dict[str, Any]:
    """Read inference engine hardware readiness and active model status."""
    return _read_json(ENGINE_STATUS_FILE, default={})


# -----------------------------------------------------------------------------
# 3. Video Source Publishing, Control & Consumption
# -----------------------------------------------------------------------------

def publish_source_status(status_dict: Dict[str, Any], catalog_dict: Optional[Dict[str, Any]] = None) -> None:
    """Publish active video source state and discovered source catalogue."""
    _atomic_write_json(SOURCE_STATUS_FILE, status_dict)
    if catalog_dict is not None:
        _atomic_write_json(SOURCE_CATALOG_FILE, catalog_dict)


def get_ipc_source_status() -> Dict[str, Any]:
    """Read active video source status from /dev/shm."""
    return _read_json(SOURCE_STATUS_FILE, default={"source_id": "none", "active_type": "none"})


def get_ipc_source_catalog() -> Dict[str, Any]:
    """Read discovered video source catalogue from /dev/shm."""
    return _read_json(
        SOURCE_CATALOG_FILE,
        default={"csi_camera_supported": False, "usb_devices": [], "media_files": []},
    )


def send_ipc_source_command(command_type: str, **kwargs) -> bool:
    """
    Dispatch a video source command (e.g. switch_source, pause, resume)
    to the video ingress microservice via /dev/shm.
    """
    cmd_payload = {
        "id": f"{int(time.time() * 1000)}",
        "command": command_type,
        "kwargs": kwargs,
        "timestamp": time.time(),
    }
    _atomic_write_json(SOURCE_COMMAND_FILE, cmd_payload)
    return True


def consume_ipc_source_command() -> Optional[Dict[str, Any]]:
    """
    Check for an unhandled video source command in /dev/shm.
    Removes the file upon reading to prevent duplicate execution.
    """
    if not SOURCE_COMMAND_FILE.exists():
        return None
    try:
        content = SOURCE_COMMAND_FILE.read_text(encoding="utf-8")
        try:
            SOURCE_COMMAND_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        if not content:
            return None
        return json.loads(content)
    except Exception:
        return None


# -----------------------------------------------------------------------------
# 4. Zero-Copy Raw Frame Buffer (Ingress -> Inference)
# -----------------------------------------------------------------------------

def publish_raw_frame(frame_data: bytes, width: int, height: int, channels: int, frame_seq: int, source_id: str) -> None:
    """Publish a captured raw video frame buffer and metadata for inference ingestion."""
    meta = {
        "width": width,
        "height": height,
        "channels": channels,
        "frame_seq": frame_seq,
        "source_id": source_id,
        "timestamp": time.time(),
    }
    _atomic_write_bytes(RAW_FRAME_BIN_FILE, frame_data)
    _atomic_write_json(RAW_FRAME_META_FILE, meta)


def get_ipc_raw_frame() -> Optional[Tuple[bytes, Dict[str, Any]]]:
    """Retrieve the latest captured raw frame buffer and metadata."""
    meta = _read_json(RAW_FRAME_META_FILE)
    if not meta:
        return None
    raw_bytes = _read_bytes(RAW_FRAME_BIN_FILE)
    if not raw_bytes:
        return None
    return raw_bytes, meta
