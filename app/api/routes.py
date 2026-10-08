"""
FastAPI versioned REST endpoints under /api/v1/.
"""

from __future__ import annotations

import asyncio
import os
import platform
import sys
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import PlainTextResponse, StreamingResponse

from app.api.schemas import (
    HealthResponse,
    LatestDetectionsResponse,
    PlaybackControlRequest,
    ReadinessResponse,
    SourceSelectionRequest,
    StatusResponse,
    SystemInfoResponse,
)
from app.core.lifecycle import get_lifecycle_manager
from app.core.logging_config import get_logger

logger = get_logger("API.ROUTES")
api_router = APIRouter(prefix="/api/v1")
_start_time = time.time()


@api_router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Liveness check: process uptime, telemetry thread state, inference thread state."""
    mgr = get_lifecycle_manager()
    telemetry_ok = mgr.telemetry_service.get_status()["active"] if mgr.telemetry_service else False
    inference_ok = mgr.inference_service.is_running() if mgr.inference_service else False

    status = "healthy" if (telemetry_ok and inference_ok) else ("degraded" if telemetry_ok else "unhealthy")

    return HealthResponse(
        status=status,
        uptime_seconds=round(time.time() - _start_time, 1),
        telemetry_active=telemetry_ok,
        inference_active=inference_ok,
    )


@api_router.get("/ready", response_model=ReadinessResponse)
def get_readiness() -> ReadinessResponse:
    """Readiness check: validates Hailo hardware, model compilation and runtime status."""
    mgr = get_lifecycle_manager()
    if not mgr.inference_engine:
        return ReadinessResponse(
            ready=False,
            hailo_ready=False,
            model_status="UNINITIALIZED",
            hef_path="",
            error_message="Lifecycle manager not initialized",
        )

    st = mgr.inference_engine.get_status()
    return ReadinessResponse(
        ready=bool(st.get("ready", False)),
        hailo_ready=os.path.exists("/dev/hailo0"),
        model_status=str(st.get("status", "UNKNOWN")),
        hef_path=str(st.get("hef_path", "")),
        error_message=st.get("error_message"),
        is_mock=bool(st.get("is_mock", False)),
    )


@api_router.get("/status", response_model=StatusResponse)
def get_status() -> StatusResponse:
    """High-level status overview of active source, inference loop, and hardware alarms."""
    mgr = get_lifecycle_manager()
    src_st = mgr.source_manager.get_status() if mgr.source_manager else {}
    inf_st = mgr.inference_service.get_stats() if mgr.inference_service else {}
    tel_st = mgr.telemetry_service.get_status() if mgr.telemetry_service else {}

    return StatusResponse(
        application_state="RUNNING" if (mgr.inference_service and mgr.inference_service.is_running()) else "IDLE",
        active_source=src_st.get("source_id", "none"),
        active_source_type=src_st.get("active_type", "none"),
        inference_running=bool(inf_st.get("is_running", False)),
        current_fps=float(inf_st.get("current_fps", 0.0)),
        alarms_count=int(tel_st.get("active_alarms_count", 0)),
    )


@api_router.get("/metrics/current")
def get_current_metrics() -> Dict[str, Any]:
    """Latest snapshot of all collected hardware and system metrics."""
    mgr = get_lifecycle_manager()
    if not mgr.telemetry_service:
        return {}
    return mgr.telemetry_service.get_current_metrics()


@api_router.get("/metrics/history")
def get_metrics_history(
    metric_name: Optional[str] = Query(None, description="Optional metric filter"),
    start_time: Optional[str] = Query(None, description="ISO-8601 start timestamp"),
    end_time: Optional[str] = Query(None, description="ISO-8601 end timestamp"),
    limit: int = Query(300, ge=1, le=5000),
    downsample: int = Query(1, ge=1, le=50),
) -> List[Dict[str, Any]]:
    """Query time-series telemetry history from SQLite with optional downsampling."""
    mgr = get_lifecycle_manager()
    if not mgr.repository:
        return []
    return mgr.repository.query_telemetry_history(
        metric_name=metric_name,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        downsample=downsample,
    )


@api_router.get("/metrics/catalog")
def get_metrics_catalog() -> List[Dict[str, Any]]:
    """Catalogue of discovered telemetry sensors, units, and interfaces."""
    mgr = get_lifecycle_manager()
    if not mgr.telemetry_service:
        return []
    return mgr.telemetry_service.get_catalog()


@api_router.get("/inference/stats")
def get_inference_stats() -> Dict[str, Any]:
    """Rolling inference latencies (mean, p95, p99), frame counts, and FPS."""
    mgr = get_lifecycle_manager()
    if not mgr.inference_service:
        return {}
    return mgr.inference_service.get_stats()


@api_router.get("/detections/latest")
def get_latest_detections() -> Dict[str, Any]:
    """Structured detection records for the most recently processed frame."""
    mgr = get_lifecycle_manager()
    if not mgr.inference_service:
        return {"count": 0, "detections": []}

    dets = mgr.inference_service.get_latest_detections()
    res = mgr.inference_service.get_latest_result()

    return {
        "count": len(dets),
        "detections": dets,
        "timestamp_utc": res.timestamp_utc if res else None,
        "image_width": res.image_width if res else 640,
        "image_height": res.image_height if res else 480,
    }


@api_router.get("/video/sources")
def get_video_sources() -> Dict[str, Any]:
    """Enumerate discovered video inputs (Pi CSI cameras, USB webcams, media files)."""
    mgr = get_lifecycle_manager()
    if not mgr.source_manager:
        return {}
    return mgr.source_manager.enumerate_sources()


@api_router.post("/video/source")
def select_video_source(req: SourceSelectionRequest) -> Dict[str, Any]:
    """Controlled source transition to Raspberry Pi CSI camera, USB webcam, or file."""
    mgr = get_lifecycle_manager()
    if not mgr.source_manager:
        raise HTTPException(status_code=500, detail="Video source manager unavailable")

    kwargs: Dict[str, Any] = {}
    if req.source_type == "picamera":
        if req.camera_num is not None:
            kwargs["camera_num"] = req.camera_num
    elif req.source_type == "usb":
        if req.device:
            kwargs["device"] = req.device
    elif req.source_type == "file":
        if req.file_path:
            kwargs["file_path"] = req.file_path
        if req.loop is not None:
            kwargs["loop"] = req.loop

    if req.width:
        kwargs["width"] = req.width
    if req.height:
        kwargs["height"] = req.height
    if req.fps:
        kwargs["fps"] = req.fps

    success = mgr.source_manager.switch_source(req.source_type, **kwargs)
    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to switch to {req.source_type}. Verify hardware connection or file format.",
        )

    return {"status": "ok", "source_info": mgr.source_manager.get_status()}


@api_router.post("/video/playback")
def control_playback(req: PlaybackControlRequest) -> Dict[str, Any]:
    """Playback controls (play, pause, restart) for prerecorded video files."""
    mgr = get_lifecycle_manager()
    if not mgr.source_manager:
        raise HTTPException(status_code=500, detail="Source manager not ready")

    if req.action == "pause":
        ok = mgr.source_manager.pause_playback()
    elif req.action == "play":
        ok = mgr.source_manager.resume_playback()
    elif req.action == "restart":
        ok = mgr.source_manager.restart_playback()
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    return {"status": "ok" if ok else "unsupported", "action": req.action}


@api_router.post("/inference/start")
def start_inference() -> Dict[str, Any]:
    """Start or resume background YOLO11 inference worker."""
    mgr = get_lifecycle_manager()
    if not mgr.inference_service:
        raise HTTPException(status_code=500, detail="Inference service not ready")

    mgr.inference_service.start()
    return {"status": "started", "running": mgr.inference_service.is_running()}


@api_router.post("/inference/stop")
def stop_inference() -> Dict[str, Any]:
    """Safely stop background inference loop."""
    mgr = get_lifecycle_manager()
    if not mgr.inference_service:
        raise HTTPException(status_code=500, detail="Inference service not ready")

    mgr.inference_service.stop()
    return {"status": "stopped", "running": False}


@api_router.get("/video/frame")
def get_latest_frame_jpeg():
    """Returns single JPEG snapshot of annotated video preview."""
    mgr = get_lifecycle_manager()
    if not mgr.inference_service:
        raise HTTPException(status_code=503, detail="Inference service not ready")

    jpeg_data = mgr.inference_service.get_latest_jpeg()
    if not jpeg_data:
        raise HTTPException(status_code=404, detail="No preview frame available yet")

    return Response(content=jpeg_data, media_type="image/jpeg")


@api_router.get("/video/stream")
async def get_mjpeg_stream():
    """Live multipart MJPEG preview stream with bounding box annotations."""
    mgr = get_lifecycle_manager()

    async def frame_generator():
        while True:
            if mgr.inference_service:
                jpeg_data = mgr.inference_service.get_latest_jpeg()
                if jpeg_data:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + jpeg_data + b"\r\n"
                    )
            await asyncio.sleep(0.066)  # ~15 fps preview delivery rate

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@api_router.get("/config/public")
def get_public_config() -> Dict[str, Any]:
    """Safe, effective non-sensitive application configuration."""
    mgr = get_lifecycle_manager()
    return mgr.config.get_public_config()


@api_router.get("/system/info", response_model=SystemInfoResponse)
def get_system_info() -> SystemInfoResponse:
    """Target hardware and runtime software discovery info."""
    cpu_model = "Unknown"
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
            for line in f:
                if "model name" in line or "Hardware" in line or "Model" in line:
                    cpu_model = line.split(":", 1)[1].strip()
                    break
    except Exception:
        pass

    hailo_pkg = False
    try:
        import hailo_platform  # type: ignore
        hailo_pkg = True
    except ImportError:
        pass

    return SystemInfoResponse(
        hostname=platform.node(),
        platform=platform.platform(),
        os_kernel=platform.release(),
        python_version=sys.version.split()[0],
        cpu_model=cpu_model,
        hailo_device_present=os.path.exists("/dev/hailo0"),
        hailo_runtime_installed=hailo_pkg,
    )


@api_router.get("/history/export/telemetry")
def export_telemetry_csv():
    """Export persisted telemetry records as CSV dataset."""
    mgr = get_lifecycle_manager()
    if not mgr.repository:
        raise HTTPException(status_code=500, detail="Repository not initialized")
    csv_str = mgr.repository.export_telemetry_csv()
    return PlainTextResponse(
        csv_str,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=telemetry_export.csv"},
    )


@api_router.get("/history/export/detections")
def export_detections_csv():
    """Export persisted detections history as CSV dataset."""
    mgr = get_lifecycle_manager()
    if not mgr.repository:
        raise HTTPException(status_code=500, detail="Repository not initialized")
    csv_str = mgr.repository.export_detections_csv()
    return PlainTextResponse(
        csv_str,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=detections_export.csv"},
    )
