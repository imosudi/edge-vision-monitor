"""
Inference worker service: pipeline coordination, rolling statistics calculation,
preview encoding, and result distribution.
"""

from __future__ import annotations

import collections
import threading
import time
from typing import Any, Deque, Dict, List, Optional
import cv2
import numpy as np

from app.core.config import ServerConfig
from app.core.ipc import publish_engine_status, publish_inference_frame
from app.core.logging_config import get_logger
from app.inference.detection import Detection, DetectionResult
from app.inference.engine import BaseInferenceEngine
from app.inference.postprocessing import annotate_frame
from app.services.event_service import EventService
from app.sources.manager import VideoSourceManager
from app.storage.models import DetectionRecord, InferenceFrameRecord
from app.storage.repository import TelemetryRepository

logger = get_logger("SERVICE.INFERENCE")


class RollingLatencyTracker:
    """Computes rolling percentiles (mean, median, p50, p95, p99, min, max) over a fixed window."""

    def __init__(self, window_size: int = 100):
        self._window_size = window_size
        self._samples: Deque[float] = collections.deque(maxlen=window_size)

    def add(self, value: float) -> None:
        self._samples.append(value)

    def get_stats(self) -> Dict[str, float]:
        if not self._samples:
            return {
                "mean": 0.0,
                "median": 0.0,
                "p50": 0.0,
                "p95": 0.0,
                "p99": 0.0,
                "min": 0.0,
                "max": 0.0,
                "count": 0.0,
            }

        sorted_vals = sorted(self._samples)
        n = len(sorted_vals)

        mean_val = sum(sorted_vals) / n
        median_val = sorted_vals[n // 2]
        p50_idx = min(int(n * 0.50), n - 1)
        p95_idx = min(int(n * 0.95), n - 1)
        p99_idx = min(int(n * 0.99), n - 1)

        return {
            "mean": round(mean_val, 2),
            "median": round(median_val, 2),
            "p50": round(sorted_vals[p50_idx], 2),
            "p95": round(sorted_vals[p95_idx], 2),
            "p99": round(sorted_vals[p99_idx], 2),
            "min": round(sorted_vals[0], 2),
            "max": round(sorted_vals[-1], 2),
            "count": float(n),
        }


class InferenceService:
    """Dedicated background service executing continuous YOLO11 inference on incoming video frames."""

    def __init__(
        self,
        engine: BaseInferenceEngine,
        source_manager: VideoSourceManager,
        repository: Optional[TelemetryRepository] = None,
        event_service: Optional[EventService] = None,
        server_config: Optional[ServerConfig] = None,
    ):
        self._engine = engine
        self._source_manager = source_manager
        self._repository = repository
        self._event_service = event_service
        self._server_config = server_config or ServerConfig()

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_running = False

        # Live Preview & Detections cache
        self._lock = threading.Lock()
        self._latest_jpeg: Optional[bytes] = None
        self._latest_detections: List[Dict[str, Any]] = []
        self._latest_result: Optional[DetectionResult] = None

        # Statistics & Rolling Metrics
        self._total_processed = 0
        self._total_dropped = 0
        self._total_errors = 0
        self._recent_fps_timestamps: Deque[float] = collections.deque(maxlen=50)
        self._last_frame_ts = 0.0
        self._last_inter_frame_ms = 0.0

        self._lat_preprocess = RollingLatencyTracker(window_size=100)
        self._lat_hailo = RollingLatencyTracker(window_size=100)
        self._lat_postprocess = RollingLatencyTracker(window_size=100)
        self._lat_total = RollingLatencyTracker(window_size=100)
        self._lat_rendering = RollingLatencyTracker(window_size=100)

        # Preview pacing and benchmark mode
        self._benchmark_mode = False
        self._last_preview_time = 0.0
        self._preview_interval = 1.0 / max(1.0, float(server_config.preview_max_fps))

    def start(self) -> bool:
        """Start the background inference loop."""
        if self._thread and self._thread.is_alive():
            return True

        if not self._engine.is_ready():
            logger.info("Initialising inference engine before start...")
            res = self._engine.initialize()
            if not res.is_valid:
                logger.warning("Inference engine not ready: %s (%s)", res.error_message, res.status)

        self._stop_event.clear()
        self._is_running = True
        self._thread = threading.Thread(
            target=self._worker_loop, name="InferenceWorkerThread", daemon=True
        )
        self._thread.start()
        publish_engine_status(self._engine.get_status())
        try:
            publish_inference_frame(
                jpeg_bytes=self.get_latest_jpeg(),
                detections=self.get_latest_detections(),
                stats=self.get_stats(),
            )
        except Exception:
            pass
        if self._event_service:
            self._event_service.emit("INFERENCE_STARTED", "Continuous object detection inference started", component="INFERENCE")
        logger.info("Inference worker service started")
        return True

    def stop(self, timeout: float = 3.0) -> None:
        """Stop the inference loop."""
        self._stop_event.set()
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None
        try:
            publish_inference_frame(
                jpeg_bytes=self.get_latest_jpeg(),
                detections=self.get_latest_detections(),
                stats=self.get_stats(),
            )
        except Exception:
            pass
        if self._event_service:
            self._event_service.emit("INFERENCE_STOPPED", "Inference execution stopped safely", component="INFERENCE")
        logger.info("Inference worker service stopped")

    def is_running(self) -> bool:
        return self._is_running and (self._thread is not None and self._thread.is_alive())

    def switch_engine(self, new_engine: BaseInferenceEngine) -> bool:
        """
        Dynamically switch active inference engine backend (e.g. Hailo-8L <-> CPU ONNX)
        safely stopping and resuming the worker thread.
        """
        was_running = self.is_running()
        if was_running:
            self.stop()

        old_engine = self._engine
        try:
            if old_engine is not None:
                try:
                    old_engine.close()
                except Exception as ce:
                    logger.warning("Error closing previous engine before switch: %s", ce)

            logger.info("Initialising new engine: %s", type(new_engine).__name__)
            res = new_engine.initialize()
            if not res.is_valid:
                logger.warning("New engine initialisation failed: %s (%s)", res.error_message, res.status)
                if old_engine is not None:
                    try:
                        old_engine.initialize()
                        self._engine = old_engine
                    except Exception:
                        pass
                if was_running:
                    self.start()
                return False

            self._engine = new_engine

            # Reset latency metrics for clear stats under new backend
            self._lat_preprocess = RollingLatencyTracker(window_size=100)
            self._lat_hailo = RollingLatencyTracker(window_size=100)
            self._lat_postprocess = RollingLatencyTracker(window_size=100)
            self._lat_total = RollingLatencyTracker(window_size=100)
            self._lat_rendering = RollingLatencyTracker(window_size=100)
            self._recent_fps_timestamps.clear()

            if was_running:
                self.start()

            st = new_engine.get_status()
            publish_engine_status(st)
            self._event_service.emit(
                "BACKEND_SWITCHED",
                f"Switched inference backend to {st.get('type', 'Unknown')} ({st.get('backend', 'unknown')})",
                component="INFERENCE",
            )
            logger.info("Successfully switched inference backend to %s", st.get("type"))
            return True
        except Exception as e:
            logger.error("Failed to switch inference engine: %s", e, exc_info=True)
            if was_running:
                self.start()
            return False

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            t_acq_start = time.monotonic()
            vframe = None
            if self._source_manager is not None:
                vframe = self._source_manager.get_frame(timeout=0.05)

            # Fallback to shared memory IPC raw frame buffer from ingress service
            if vframe is None or vframe.data is None:
                try:
                    from app.core.ipc import get_ipc_raw_frame
                    raw_frame = get_ipc_raw_frame()
                    if raw_frame is not None:
                        raw_bytes, meta = raw_frame
                        seq = meta.get("frame_seq", 0)
                        if seq != getattr(self, "_last_ipc_seq", -1):
                            self._last_ipc_seq = seq
                            w = meta.get("width", 640)
                            h = meta.get("height", 480)
                            c = meta.get("channels", 3)
                            frame_data = np.frombuffer(raw_bytes, dtype=np.uint8).reshape((h, w, c)).copy()
                            from app.sources.base import VideoFrame
                            vframe = VideoFrame(
                                frame_seq=seq,
                                data=frame_data,
                                source_id=meta.get("source_id", "ipc:ingress"),
                                width=w,
                                height=h,
                                monotonic_ts=meta.get("timestamp", time.monotonic()),
                            )
                except Exception as e:
                    logger.warning("Error reading raw frame from IPC: %s", e)

            if vframe is None or vframe.data is None:
                # No frame available from source or IPC right now
                time.sleep(0.01)
                continue

            acq_ms = (time.monotonic() - t_acq_start) * 1000.0

            try:
                # 1. Execute Inference
                now_check = time.monotonic()
                is_preview_frame = (now_check - self._last_preview_time) >= self._preview_interval
                skip_post = self._benchmark_mode and not is_preview_frame

                result = self._engine.infer(
                    frame=vframe.data,
                    frame_seq=vframe.frame_seq,
                    source_id=vframe.source_id,
                    skip_postprocessing=skip_post,
                )
                result.acquisition_ms = acq_ms

                now = time.monotonic()
                if self._last_frame_ts > 0.0:
                    self._last_inter_frame_ms = round((now - self._last_frame_ts) * 1000.0, 1)
                else:
                    self._last_inter_frame_ms = 0.0
                self._last_frame_ts = now

                self._total_processed += 1
                self._recent_fps_timestamps.append(now)

                # 2. Update Rolling Latencies
                self._lat_preprocess.add(result.preprocessing_ms)
                self._lat_hailo.add(result.hailo_exec_ms)
                if not skip_post:
                    self._lat_postprocess.add(result.postprocessing_ms)
                self._lat_total.add(result.total_latency_ms)

                # 3. Render Preview JPEG if interval elapsed
                if (now - self._last_preview_time) >= self._preview_interval:
                    t_render_start = time.monotonic()
                    annotated = annotate_frame(vframe.data, result.detections)
                    ret, jpeg_bytes = cv2.imencode(
                        ".jpg",
                        annotated,
                        [int(cv2.IMWRITE_JPEG_QUALITY), self._server_config.preview_quality],
                    )
                    if ret:
                        with self._lock:
                            self._latest_jpeg = jpeg_bytes.tobytes()
                    render_ms = (time.monotonic() - t_render_start) * 1000.0
                    self._lat_rendering.add(render_ms)
                    self._last_preview_time = now

                # 4. Cache structured detections and publish to shared-memory IPC
                with self._lock:
                    if not skip_post:
                        self._latest_detections = [d.to_dict() for d in result.detections]
                    self._latest_result = result
                    publish_inference_frame(
                        jpeg_bytes=self._latest_jpeg,
                        detections=self._latest_detections,
                        stats=self.get_stats(),
                        frame_seq=result.frame_seq,
                        timestamp_utc=result.timestamp_utc,
                        image_width=vframe.data.shape[1] if vframe.data is not None else 640,
                        image_height=vframe.data.shape[0] if vframe.data is not None else 480,
                    )

                # 5. Enqueue Persistence Records
                frame_rec = InferenceFrameRecord(
                    frame_seq=result.frame_seq,
                    source_id=result.source_id,
                    timestamp_utc=result.timestamp_utc,
                    acquisition_ms=result.acquisition_ms,
                    preprocessing_ms=result.preprocessing_ms,
                    hailo_exec_ms=result.hailo_exec_ms,
                    postprocessing_ms=result.postprocessing_ms,
                    total_latency_ms=result.total_latency_ms,
                    detections_count=len(result.detections),
                    error_status=result.error_status,
                )
                det_recs = [
                    DetectionRecord(
                        frame_seq=result.frame_seq,
                        timestamp_utc=result.timestamp_utc,
                        class_id=d.class_id,
                        class_name=d.class_name,
                        confidence=d.confidence,
                        box_xmin=d.box.xmin,
                        box_ymin=d.box.ymin,
                        box_xmax=d.box.xmax,
                        box_ymax=d.box.ymax,
                    )
                    for d in result.detections
                ]
                if self._repository is not None:
                    self._repository.enqueue_inference(frame_rec, det_recs)

            except Exception as e:
                self._total_errors += 1
                logger.error("Error during inference loop execution: %s", e, exc_info=True)
                time.sleep(0.05)

    def get_current_fps(self) -> float:
        """Calculate current inference FPS over recent frames."""
        if len(self._recent_fps_timestamps) < 2:
            return 0.0
        duration = self._recent_fps_timestamps[-1] - self._recent_fps_timestamps[0]
        if duration <= 0:
            return 0.0
        return round((len(self._recent_fps_timestamps) - 1) / duration, 1)

    def reset_stats(self) -> None:
        """Reset rolling latency stats, frame counters, and cached detections."""
        with self._lock:
            self._total_processed = 0
            self._total_dropped = 0
            self._total_errors = 0
            self._recent_fps_timestamps.clear()
            self._last_frame_ts = 0.0
            self._last_inter_frame_ms = 0.0
            self._lat_preprocess = RollingLatencyTracker(window_size=100)
            self._lat_hailo = RollingLatencyTracker(window_size=100)
            self._lat_postprocess = RollingLatencyTracker(window_size=100)
            self._lat_total = RollingLatencyTracker(window_size=100)
            self._lat_rendering = RollingLatencyTracker(window_size=100)
            self._latest_detections.clear()
            self._latest_result = None
        try:
            publish_inference_frame(
                jpeg_bytes=self.get_latest_jpeg(),
                detections=self.get_latest_detections(),
                stats=self.get_stats(),
            )
        except Exception:
            pass
        logger.info("Inference rolling statistics and detection caches reset")

    def get_stats(self) -> Dict[str, Any]:
        """Return comprehensive rolling inference performance metrics."""
        eng_st = self._engine.get_status()
        active_backend = eng_st.get("backend", "hailo" if "Hailo" in eng_st.get("type", "") else "cpu")
        return {
            "is_running": self.is_running(),
            "active_backend": active_backend,
            "benchmark_mode": self._benchmark_mode,
            "engine_status": eng_st,
            "current_fps": self.get_current_fps(),
            "inter_frame_ms": self._last_inter_frame_ms,
            "total_frames_processed": self._total_processed,
            "total_errors": self._total_errors,
            "latencies": {
                "preprocessing_ms": self._lat_preprocess.get_stats(),
                "execution_ms": self._lat_hailo.get_stats(),
                "hailo_execution_ms": self._lat_hailo.get_stats(),
                "postprocessing_ms": self._lat_postprocess.get_stats(),
                "rendering_ms": self._lat_rendering.get_stats(),
                "total_ms": self._lat_total.get_stats(),
            },
        }

    def set_benchmark_mode(self, enabled: bool) -> None:
        """
        Toggle high-throughput benchmark mode.
        When enabled, preview encoding is throttled to 2 FPS to decouple CPU image
        compression from maximum accelerator inference throughput.
        """
        with self._lock:
            self._benchmark_mode = enabled
            if enabled:
                self._preview_interval = 0.5  # Max 2 FPS preview during benchmarks
            else:
                self._preview_interval = 1.0 / max(1.0, float(self._server_config.preview_max_fps))
        logger.info("InferenceService benchmark mode %s", "enabled" if enabled else "disabled")

    def get_latency_percentiles(self) -> Dict[str, Dict[str, float]]:
        """Return rolling latency percentiles (p50, p95, p99) across all pipeline stages."""
        return {
            "preprocessing": self._lat_preprocess.get_stats(),
            "execution": self._lat_hailo.get_stats(),
            "postprocessing": self._lat_postprocess.get_stats(),
            "rendering": self._lat_rendering.get_stats(),
            "total": self._lat_total.get_stats(),
        }

    def get_latest_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._latest_jpeg

    def get_latest_detections(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._latest_detections)

    def get_latest_result(self) -> Optional[DetectionResult]:
        with self._lock:
            return self._latest_result
