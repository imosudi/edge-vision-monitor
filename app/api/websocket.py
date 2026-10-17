"""
High-frequency WebSocket endpoint for real-time dashboard updates and live telemetry distribution.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.lifecycle import get_lifecycle_manager
from app.core.logging_config import get_logger

logger = get_logger("API.WEBSOCKET")
ws_router = APIRouter()


class WebSocketManager:
    """Manages active dashboard WebSocket clients and broadcasts live status."""

    def __init__(self):
        self._active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._active_connections.add(websocket)
        logger.debug("WebSocket client connected (total active: %d)", len(self._active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        self._active_connections.discard(websocket)
        logger.debug("WebSocket client disconnected (remaining: %d)", len(self._active_connections))

    async def broadcast(self, data: dict) -> None:
        if not self._active_connections:
            return

        payload = json.dumps(data)
        stale_connections = []
        for conn in self._active_connections:
            try:
                await conn.send_text(payload)
            except Exception:
                stale_connections.append(conn)

        for stale in stale_connections:
            self._active_connections.discard(stale)


ws_manager = WebSocketManager()


@ws_router.websocket("/api/v1/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket streaming endpoint. Broadcasts live telemetry and inference updates at ~5 Hz.
    """
    await ws_manager.connect(websocket)
    mgr = get_lifecycle_manager()

    try:
        while True:
            # Prepare combined snapshot
            now_utc = datetime.now(timezone.utc).isoformat()
            if mgr.telemetry_service:
                metrics_snapshot = mgr.telemetry_service.get_current_metrics()
            else:
                from app.core.ipc import get_ipc_telemetry_metrics
                metrics_snapshot = get_ipc_telemetry_metrics()

            if mgr.inference_service:
                inf_stats = mgr.inference_service.get_stats()
                detections = mgr.inference_service.get_latest_detections()
            else:
                from app.core.ipc import get_ipc_inference_stats, get_ipc_latest_detections, get_ipc_engine_status
                inf_stats = get_ipc_inference_stats()
                det_data = get_ipc_latest_detections()
                detections = det_data.get("detections", [])
                if "engine_status" not in inf_stats:
                    eng_st = get_ipc_engine_status()
                    if eng_st:
                        inf_stats["engine_status"] = eng_st
                        inf_stats["active_backend"] = eng_st.get("backend", "hailo" if "Hailo" in eng_st.get("type", "") else "cpu")

            if mgr.source_manager:
                src_st = mgr.source_manager.get_status()
            else:
                from app.core.ipc import get_ipc_source_status
                src_st = get_ipc_source_status()

            payload = {
                "type": "telemetry_update",
                "timestamp_utc": now_utc,
                "status": {
                    "inference_running": bool(inf_stats.get("is_running", False)),
                    "active_source": src_st.get("source_id", "none"),
                    "source_type": src_st.get("active_type", "none"),
                    "active_backend": inf_stats.get("active_backend", "hailo"),
                },
                "inference": {
                    "active_backend": inf_stats.get("active_backend", "hailo"),
                    "backend_name": inf_stats.get("engine_status", {}).get("type", "Hailo-8L"),
                    "fps": inf_stats.get("current_fps", 0.0),
                    "inter_frame_ms": inf_stats.get("inter_frame_ms", 0.0),
                    "latencies": inf_stats.get("latencies", {}),
                    "total_frames": inf_stats.get("total_frames_processed", 0),
                    "detections_count": len(detections),
                },
                "detections": detections,
                "metrics": metrics_snapshot,
            }

            await websocket.send_text(json.dumps(payload))

            # Sleep ~200ms (5 updates/sec)
            await asyncio.sleep(0.2)

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.debug("WebSocket error: %s", e)
        ws_manager.disconnect(websocket)


@ws_router.websocket("/api/v1/video/browser-stream")
async def browser_stream_endpoint(websocket: WebSocket):
    """
    High-frequency bidirectional WebSocket endpoint for streaming video frames
    directly from client web browser device camera to YOLO11 inference engine.
    """
    await websocket.accept()
    logger.info("Client browser camera WebSocket connected")
    mgr = get_lifecycle_manager()
    seq = 0
    try:
        while True:
            frame_bytes = await websocket.receive_bytes()
            if not frame_bytes:
                continue
            seq += 1
            from app.api.routes import handle_browser_camera_frame
            handle_browser_camera_frame(mgr, frame_bytes, seq)
    except WebSocketDisconnect:
        logger.info("Client browser camera WebSocket disconnected")
    except Exception as e:
        logger.debug("Browser camera WebSocket stream closed: %s", e)

