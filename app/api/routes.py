"""
FastAPI versioned REST endpoints under /api/v1/.
"""

from __future__ import annotations

import asyncio
import os
import platform
import re
import sys
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse

from app.api.schemas import (
    BackendDetail,
    BackendSelectionRequest,
    BackendsResponse,
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

    if mgr.service_mode == "gateway":
        status = "healthy"
    else:
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
        from app.core.ipc import get_ipc_engine_status
        ipc_st = get_ipc_engine_status()
        if ipc_st:
            current_backend = ipc_st.get("backend", "hailo" if "Hailo" in ipc_st.get("type", "") else "cpu")
            is_hailo_ready = (
                os.path.exists("/dev/hailo0")
                or bool(ipc_st.get("hailo_ready", False))
                or (current_backend == "hailo" and bool(ipc_st.get("ready", False)))
            )
            return ReadinessResponse(
                ready=bool(ipc_st.get("ready", False)),
                active_backend=current_backend,
                hailo_ready=is_hailo_ready,
                model_status=str(ipc_st.get("status", "UNKNOWN")),
                model_path=str(ipc_st.get("model_path", ipc_st.get("hef_path", ""))),
                hef_path=str(ipc_st.get("hef_path", "")),
                error_message=ipc_st.get("error_message"),
                is_mock=bool(ipc_st.get("is_mock", False)),
            )
        return ReadinessResponse(
            ready=False,
            active_backend="none",
            hailo_ready=os.path.exists("/dev/hailo0"),
            model_status="UNINITIALIZED",
            model_path="",
            hef_path="",
            error_message="Lifecycle manager or inference engine not initialised",
            is_mock=False,
        )

    st = mgr.inference_engine.get_status()
    current_backend = st.get("backend", "hailo" if "Hailo" in st.get("type", "") else "cpu")
    is_hailo_ready = (
        os.path.exists("/dev/hailo0")
        or bool(st.get("hailo_ready", False))
        or (current_backend == "hailo" and bool(st.get("ready", False)))
    )
    return ReadinessResponse(
        ready=bool(st.get("ready", False)),
        active_backend=current_backend,
        hailo_ready=is_hailo_ready,
        model_status=str(st.get("status", "UNKNOWN")),
        model_path=str(st.get("model_path", st.get("hef_path", ""))),
        hef_path=str(st.get("hef_path", "")),
        error_message=st.get("error_message"),
        is_mock=bool(st.get("is_mock", False)),
    )


@api_router.get("/status", response_model=StatusResponse)
def get_status() -> StatusResponse:
    """High-level status overview of active source, inference loop, and hardware alarms."""
    mgr = get_lifecycle_manager()
    from app.core.ipc import get_ipc_inference_stats, get_ipc_source_status, get_ipc_telemetry_status
    src_st = mgr.source_manager.get_status() if mgr.source_manager else get_ipc_source_status()
    inf_st = mgr.inference_service.get_stats() if mgr.inference_service else get_ipc_inference_stats()
    tel_st = mgr.telemetry_service.get_status() if mgr.telemetry_service else get_ipc_telemetry_status()

    is_running = (mgr.inference_service and mgr.inference_service.is_running()) or bool(inf_st.get("is_running", False))

    return StatusResponse(
        application_state="RUNNING" if is_running else "IDLE",
        active_source=src_st.get("source_id", "none"),
        active_source_type=src_st.get("active_type", "none"),
        active_backend=inf_st.get("active_backend", "hailo"),
        inference_running=is_running,
        current_fps=float(inf_st.get("current_fps", 0.0)),
        alarms_count=int(tel_st.get("active_alarms_count", 0)),
    )


@api_router.get("/metrics/current")
def get_current_metrics() -> Dict[str, Any]:
    """Latest snapshot of all collected hardware and system metrics."""
    mgr = get_lifecycle_manager()
    if mgr.telemetry_service:
        return mgr.telemetry_service.get_current_metrics()
    from app.core.ipc import get_ipc_telemetry_metrics
    return get_ipc_telemetry_metrics()


@api_router.get("/metrics/history")
def get_metrics_history(
    metric_name: Optional[str] = Query(None, description="Optional metric filter"),
    start_time: Optional[str] = Query(None, description="ISO-8601 start timestamp"),
    end_time: Optional[str] = Query(None, description="ISO-8601 end timestamp"),
    limit: int = Query(300, ge=1, le=5000),
    downsample: int = Query(1, ge=1, le=50),
    target_points: Optional[int] = Query(None, ge=10, le=5000, description="Target number of points"),
    method: str = Query("stride", description="Downsampling method: 'stride', 'bucket', or 'lttb'"),
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
        target_points=target_points,
        method=method,
    )


@api_router.get("/metrics/downsampled")
def get_downsampled_metrics(
    metric_name: str = Query(..., description="Target metric name to downsample"),
    start_time: Optional[str] = Query(None, description="ISO-8601 start timestamp"),
    end_time: Optional[str] = Query(None, description="ISO-8601 end timestamp"),
    target_points: int = Query(100, ge=10, le=2000, description="Target number of downsampled points"),
    method: str = Query("lttb", description="Downsample algorithm: 'lttb' or 'bucket'"),
) -> List[Dict[str, Any]]:
    """Query high-performance downsampled time-series tailored for responsive charting."""
    mgr = get_lifecycle_manager()
    if not mgr.repository:
        return []
    return mgr.repository.query_downsampled_metrics(
        metric_name=metric_name,
        start_time=start_time,
        end_time=end_time,
        target_points=target_points,
        method=method,
    )


@api_router.get("/metrics/catalog")
def get_metrics_catalog() -> List[Dict[str, Any]]:
    """Catalogue of discovered telemetry sensors, units, and interfaces."""
    mgr = get_lifecycle_manager()
    if mgr.telemetry_service:
        return mgr.telemetry_service.get_catalog()
    from app.core.ipc import get_ipc_telemetry_catalog
    return get_ipc_telemetry_catalog()


@api_router.get("/inference/history")
def get_inference_history(
    start_time: Optional[str] = Query(None, description="ISO-8601 start timestamp"),
    end_time: Optional[str] = Query(None, description="ISO-8601 end timestamp"),
    limit: int = Query(50, ge=1, le=1000),
) -> List[Dict[str, Any]]:
    """Query recent historical frame inference records."""
    mgr = get_lifecycle_manager()
    if not mgr.repository:
        return []
    return mgr.repository.query_inference_history(
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )


@api_router.get("/detections/history")
def get_detections_history(
    start_time: Optional[str] = Query(None, description="ISO-8601 start timestamp"),
    end_time: Optional[str] = Query(None, description="ISO-8601 end timestamp"),
    class_name: Optional[str] = Query(None, description="Optional class filter"),
    limit: int = Query(500, ge=1, le=2000),
) -> List[Dict[str, Any]]:
    """Query recent historical object detections."""
    mgr = get_lifecycle_manager()
    if not mgr.repository:
        return []
    return mgr.repository.query_detections_history(
        start_time=start_time,
        end_time=end_time,
        class_name=class_name,
        limit=limit,
    )


@api_router.get("/inference/stats")
def get_inference_stats() -> Dict[str, Any]:
    """Rolling inference latencies (mean, p95, p99), frame counts, and FPS."""
    mgr = get_lifecycle_manager()
    if mgr.inference_service:
        return mgr.inference_service.get_stats()
    from app.core.ipc import get_ipc_inference_stats
    return get_ipc_inference_stats()


@api_router.get("/detections/latest")
def get_latest_detections() -> Dict[str, Any]:
    """Structured detection records for the most recently processed frame."""
    mgr = get_lifecycle_manager()
    if mgr.inference_service:
        dets = mgr.inference_service.get_latest_detections()
        res = mgr.inference_service.get_latest_result()
        return {
            "count": len(dets),
            "detections": dets,
            "timestamp_utc": res.timestamp_utc if res else None,
            "image_width": res.image_width if res else 640,
            "image_height": res.image_height if res else 480,
        }

    from app.core.ipc import get_ipc_latest_detections
    return get_ipc_latest_detections()


@api_router.get("/video/sources")
def get_video_sources() -> Dict[str, Any]:
    """Enumerate discovered video inputs (Pi CSI cameras, USB webcams, media files)."""
    mgr = get_lifecycle_manager()
    if mgr.source_manager:
        return mgr.source_manager.enumerate_sources()
    from app.core.ipc import get_ipc_source_catalog
    return get_ipc_source_catalog()


@api_router.post("/video/source")
def select_video_source(req: SourceSelectionRequest) -> Dict[str, Any]:
    """Controlled source transition to Raspberry Pi CSI camera, USB webcam, or file."""
    mgr = get_lifecycle_manager()

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

    if mgr.source_manager:
        success = mgr.source_manager.switch_source(req.source_type, **kwargs)
        st = mgr.source_manager.get_status()
        if not success or st.get("active_type") != req.source_type:
            detail = st.get("error_status") or f"Failed to switch to {req.source_type}. Verify hardware connection or system permissions."
            raise HTTPException(status_code=400, detail=detail)
        return {"status": "ok", "source_info": st}

    # Microservices decomposition fallback via shared-memory IPC
    import time
    from app.core.ipc import get_ipc_source_catalog, get_ipc_source_status, send_ipc_source_command
    send_ipc_source_command("switch_source", source_type=req.source_type, **kwargs)
    deadline = time.time() + 3.0
    st: Dict[str, Any] = {}
    while time.time() < deadline:
        time.sleep(0.1)
        st = get_ipc_source_status()
        if st.get("active_type") == req.source_type:
            break
        if st.get("error_status"):
            break
    if st.get("active_type") != req.source_type:
        detail = st.get("error_status")
        if not detail:
            if req.source_type == "picamera":
                detail = "Picamera2 is not installed or accessible in this container environment. Ensure libcamera, python3-picamera2, and Raspberry Pi camera device mappings (/dev, /run/udev, /sys) are present."
            else:
                detail = f"Failed to switch to {req.source_type}. Verify hardware connection or file format."
        raise HTTPException(status_code=400, detail=detail)
    return {"status": "ok", "source_info": st}


ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mkv", ".mov", ".m4v", ".webm"}


@api_router.post("/video/upload")
async def upload_video_file(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Upload prerecorded video file to media directory for accelerated playback and testing."""
    mgr = get_lifecycle_manager()
    media_dir = "media"
    if mgr.config and mgr.config.video and mgr.config.video.media_dir:
        media_dir = mgr.config.video.media_dir

    os.makedirs(media_dir, exist_ok=True)

    # Sanitize filename (remove directory components, restrict characters)
    original_name = os.path.basename(file.filename or "video.mp4")
    name_clean = re.sub(r"[^a-zA-Z0-9_.-]", "_", original_name)
    ext = os.path.splitext(name_clean)[1].lower()

    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported video file extension '{ext}'. Allowed: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}",
        )

    target_path = os.path.join(media_dir, name_clean)

    # Stream file to disk in chunks to avoid buffering large video in memory
    total_bytes = 0
    try:
        with open(target_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):  # 1MB chunks
                buffer.write(chunk)
                total_bytes += len(chunk)
    except Exception as e:
        if os.path.exists(target_path):
            os.remove(target_path)
        logger.error("Failed to save uploaded video file: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to save video: {e}")

    logger.info("Uploaded video file '%s' (%d bytes) saved to '%s'", name_clean, total_bytes, target_path)

    # Automatically switch video source to newly uploaded video file
    target_fps = mgr.config.video.capture_fps if (mgr.config and mgr.config.video) else 30
    if mgr.source_manager:
        mgr.source_manager.switch_source(
            "file",
            file_path=target_path,
            loop=True,
            target_fps=target_fps,
        )
    else:
        from app.core.ipc import send_ipc_source_command
        send_ipc_source_command(
            "switch_source",
            source_type="file",
            file_path=target_path,
            loop=True,
            target_fps=target_fps,
        )

    from app.core.ipc import get_ipc_source_catalog, get_ipc_source_status
    return {
        "status": "ok",
        "filename": name_clean,
        "file_path": target_path,
        "size_bytes": total_bytes,
        "media_files": mgr.source_manager.enumerate_sources().get("media_files", []) if mgr.source_manager else get_ipc_source_catalog().get("media_files", [name_clean]),
        "active_source": mgr.source_manager.get_status() if mgr.source_manager else get_ipc_source_status(),
    }


@api_router.post("/video/playback")
def control_playback(req: PlaybackControlRequest) -> Dict[str, Any]:
    """Playback controls (play, pause, restart) for prerecorded video files."""
    mgr = get_lifecycle_manager()
    if mgr.source_manager:
        if req.action == "pause":
            ok = mgr.source_manager.pause_playback()
        elif req.action == "play":
            ok = mgr.source_manager.resume_playback()
        elif req.action == "restart":
            ok = mgr.source_manager.restart_playback()
        else:
            raise HTTPException(status_code=400, detail="Invalid action")
        return {"status": "ok" if ok else "unsupported", "action": req.action}

    from app.core.ipc import send_ipc_source_command
    send_ipc_source_command(req.action)
    return {"status": "ok", "action": req.action}


@api_router.post("/inference/start")
def start_inference(
    reset_history: bool = Query(True, description="Reset telemetry and detection history for fresh run"),
) -> Dict[str, Any]:
    """Start or resume background YOLO11 inference worker, resetting session history by default."""
    mgr = get_lifecycle_manager()
    if mgr.inference_service:
        if reset_history:
            if mgr.repository:
                mgr.repository.reset_history()
            mgr.inference_service.reset_stats()
        mgr.inference_service.start()
        return {"status": "started", "running": mgr.inference_service.is_running()}

    # Gateway microservice mode: delegate control via shared-memory IPC
    from app.core.ipc import send_ipc_inference_command
    send_ipc_inference_command("start", reset_history=reset_history)
    return {"status": "started", "running": True}


@api_router.post("/history/reset")
def reset_history_endpoint() -> Dict[str, Any]:
    """
    Explicitly reset persisted telemetry records, frame inference history, and object detections.
    Also clears in-memory rolling statistics for a fresh detection run.
    """
    mgr = get_lifecycle_manager()
    deleted = {}
    if mgr.repository:
        deleted = mgr.repository.reset_history()
    if mgr.inference_service:
        mgr.inference_service.reset_stats()
    else:
        from app.core.ipc import send_ipc_inference_command
        send_ipc_inference_command("reset_stats")
    return {"status": "ok", "deleted": deleted}


@api_router.post("/inference/stop")
def stop_inference() -> Dict[str, Any]:
    """Safely stop background inference loop."""
    mgr = get_lifecycle_manager()
    if mgr.inference_service:
        mgr.inference_service.stop()
        return {"status": "stopped", "running": False}

    # Gateway microservice mode: delegate control via shared-memory IPC
    from app.core.ipc import send_ipc_inference_command
    send_ipc_inference_command("stop")
    return {"status": "stopped", "running": False}


@api_router.get("/inference/backends", response_model=BackendsResponse)
def get_backends() -> BackendsResponse:
    """Check hardware and model file availability for Hailo, CPU, and Mock backends."""
    mgr = get_lifecycle_manager()
    if not mgr.inference_engine:
        from app.core.ipc import get_ipc_backends_catalog, get_ipc_engine_status
        catalog = get_ipc_backends_catalog()
        if catalog and "backends" in catalog:
            ipc_st = get_ipc_engine_status()
            if ipc_st:
                catalog["current_backend"] = ipc_st.get("backend", "hailo" if "Hailo" in ipc_st.get("type", "") else "cpu")
            return BackendsResponse(**catalog)

        data = mgr.get_available_backends()
        ipc_st = get_ipc_engine_status()
        if ipc_st:
            current = ipc_st.get("backend", "hailo" if "Hailo" in ipc_st.get("type", "") else "cpu")
            data["current_backend"] = current
            if ipc_st.get("hailo_ready") or (ipc_st.get("ready") and current == "hailo"):
                data["backends"]["hailo"]["available"] = True
                data["backends"]["hailo"]["runtime_installed"] = True
        return BackendsResponse(**data)

    data = mgr.get_available_backends()
    return BackendsResponse(**data)


@api_router.post("/inference/backend")
def switch_backend(req: BackendSelectionRequest) -> Dict[str, Any]:
    """Dynamically switch active inference backend (e.g. 'hailo' <-> 'cpu')."""
    mgr = get_lifecycle_manager()
    logger.info("Received request to switch inference backend to '%s' (model_path=%s)", req.backend, req.model_path)
    if mgr.inference_engine and mgr.inference_service:
        ok = mgr.switch_inference_backend(req.backend, model_path=req.model_path)
        if not ok:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to switch inference backend to '{req.backend}'. Verify model file exists and required runtime is available.",
            )
        return {
            "status": "switched",
            "backend": req.backend,
            "inference_running": mgr.inference_service.is_running(),
            "engine_status": mgr.inference_engine.get_status(),
        }

    # Gateway microservice mode: delegate control via shared-memory IPC
    import time
    from app.core.ipc import send_ipc_inference_command, get_ipc_engine_status
    send_ipc_inference_command("switch_backend", backend=req.backend, model_path=req.model_path)
    time.sleep(0.05)
    return {
        "status": "switched",
        "backend": req.backend,
        "inference_running": True,
        "engine_status": get_ipc_engine_status(),
    }


@api_router.get("/video/frame")
def get_latest_frame_jpeg():
    """Returns single JPEG snapshot of annotated video preview."""
    mgr = get_lifecycle_manager()
    jpeg_data = None
    if mgr.inference_service:
        jpeg_data = mgr.inference_service.get_latest_jpeg()
    else:
        from app.core.ipc import get_ipc_latest_jpeg
        jpeg_data = get_ipc_latest_jpeg()

    if not jpeg_data:
        raise HTTPException(status_code=404, detail="No preview frame available yet")

    return Response(content=jpeg_data, media_type="image/jpeg")


@api_router.get("/video/stream")
async def get_mjpeg_stream():
    """Live multipart MJPEG preview stream with bounding box annotations."""
    mgr = get_lifecycle_manager()
    from app.core.ipc import get_ipc_latest_jpeg

    async def frame_generator():
        while True:
            jpeg_data = None
            if mgr.inference_service:
                jpeg_data = mgr.inference_service.get_latest_jpeg()
            else:
                jpeg_data = get_ipc_latest_jpeg()

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


@api_router.get("/storage/status")
def get_storage_status() -> Dict[str, Any]:
    """Database file sizes, WAL status, record counts, and automated retention history."""
    mgr = get_lifecycle_manager()
    if not mgr.repository:
        raise HTTPException(status_code=500, detail="Storage repository not initialised")
    return mgr.repository.get_storage_stats()


@api_router.post("/storage/prune")
def trigger_retention_prune(
    retention_hours: Optional[float] = Query(None, ge=0.1, description="Optional override for retention threshold in hours"),
) -> Dict[str, Any]:
    """Trigger on-demand retention pruning to purge expired records and manage database size."""
    mgr = get_lifecycle_manager()
    if not mgr.repository:
        raise HTTPException(status_code=500, detail="Storage repository not initialised")
    return mgr.repository.prune_retention(retention_hours=retention_hours)


@api_router.get("/history/export/telemetry")
def export_telemetry_csv(
    metric_name: Optional[str] = Query(None, description="Optional metric filter"),
    start_time: Optional[str] = Query(None, description="ISO-8601 start timestamp"),
    end_time: Optional[str] = Query(None, description="ISO-8601 end timestamp"),
    limit: int = Query(50000, ge=1, le=500000),
):
    """Export persisted telemetry records as streaming CSV dataset."""
    mgr = get_lifecycle_manager()
    if not mgr.repository:
        raise HTTPException(status_code=500, detail="Repository not initialised")
    return StreamingResponse(
        mgr.repository.stream_telemetry_csv(
            metric_name=metric_name,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        ),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=telemetry_export.csv"},
    )


@api_router.get("/history/export/detections")
def export_detections_csv(
    start_time: Optional[str] = Query(None, description="ISO-8601 start timestamp"),
    end_time: Optional[str] = Query(None, description="ISO-8601 end timestamp"),
    class_name: Optional[str] = Query(None, description="Optional class filter"),
    limit: int = Query(50000, ge=1, le=500000),
):
    """Export persisted detections history as streaming CSV dataset."""
    mgr = get_lifecycle_manager()
    if not mgr.repository:
        raise HTTPException(status_code=500, detail="Repository not initialised")
    return StreamingResponse(
        mgr.repository.stream_detections_csv(
            start_time=start_time,
            end_time=end_time,
            class_name=class_name,
            limit=limit,
        ),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=detections_export.csv"},
    )


@api_router.get("/history/export/waveforms")
def export_waveforms_csv(
    start_time: Optional[str] = Query(None, description="ISO-8601 start timestamp"),
    end_time: Optional[str] = Query(None, description="ISO-8601 end timestamp"),
    limit: int = Query(50000, ge=1, le=500000),
):
    """Export unified multi-channel telemetry and inference waveforms as streaming CSV dataset."""
    mgr = get_lifecycle_manager()
    if not mgr.repository:
        raise HTTPException(status_code=500, detail="Repository not initialised")
    return StreamingResponse(
        mgr.repository.stream_waveforms_csv(
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        ),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=waveforms_telemetry_export.csv"},
    )

