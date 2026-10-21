"""
High-throughput unthrottled in-memory ring-buffer video source designed for
accelerator throughput benchmarking and pipeline saturation (Workload A).
Pre-decodes video frames into RAM to eliminate disk I/O and CPU decoding bottlenecks.
"""

from __future__ import annotations

import collections
import os
import threading
import time
from typing import Any, Deque, Dict, List, Optional
import cv2
import numpy as np

from app.core.logging_config import get_logger
from app.sources.base import BaseVideoSource, VideoFrame

logger = get_logger("SOURCE.RING_BUFFER")


class RingBufferVideoSource(BaseVideoSource):
    """
    In-memory circular frame buffer delivering pre-decoded frames with sub-millisecond
    acquisition latency for pure accelerator benchmarking (Workload A).
    """

    def __init__(
        self,
        file_path: Optional[str] = None,
        media_dir: str = "media",
        buffer_size: int = 120,
        unthrottled: bool = True,
        target_fps: Optional[float] = None,
    ):
        self._media_dir = os.path.abspath(media_dir)
        self._requested_path = file_path
        self._buffer_size = max(10, buffer_size)
        self._unthrottled = unthrottled
        self._target_fps = target_fps or 30.0

        self._frames: List[np.ndarray] = []
        self._current_idx = 0
        self._frame_seq = 0
        self._is_active = False
        self._synthetic_mode = False
        self._resolved_path: Optional[str] = None
        self._source_id = "ring_buffer:init"
        self._lock = threading.RLock()

        # Throughput tracking
        self._fps_timestamps: Deque[float] = collections.deque(maxlen=100)
        self._last_frame_time = 0.0
        self._min_frame_interval = (1.0 / self._target_fps) if not self._unthrottled else 0.0

    def _resolve_path(self) -> Optional[str]:
        if not self._requested_path:
            return None
        abs_p = os.path.abspath(self._requested_path)
        if os.path.exists(abs_p):
            return abs_p
        candidate = os.path.join(self._media_dir, os.path.basename(self._requested_path))
        if os.path.exists(candidate):
            return candidate
        return None

    def _generate_synthetic_frames(self, count: int) -> List[np.ndarray]:
        """Pre-generate varied procedural frames with moving objects for benchmarking."""
        frames: List[np.ndarray] = []
        for i in range(count):
            img = np.zeros((480, 640, 3), dtype=np.uint8)
            t = i * 0.08
            bg = int(25 + 15 * np.sin(t * 0.5))
            img[:] = (bg, bg + 5, bg + 10)

            # Grid lines
            for x in range(0, 640, 40):
                cv2.line(img, (x, 0), (x, 480), (35, 40, 50), 1)
            for y in range(0, 480, 40):
                cv2.line(img, (0, y), (640, y), (35, 40, 50), 1)

            # Simulated car bounding box
            x1 = int(320 + 200 * np.sin(t))
            y1 = int(240 + 80 * np.cos(t))
            cv2.rectangle(img, (x1 - 40, y1 - 25), (x1 + 40, y1 + 25), (45, 120, 240), -1)

            # Simulated person bounding box
            x2 = int(250 + 130 * np.cos(t * 1.4))
            y2 = int(200 + 100 * np.sin(t * 1.4))
            cv2.circle(img, (x2, y2), 26, (80, 220, 100), -1)

            # Telemetry watermark
            cv2.putText(
                img,
                f"RING-BUFFER BENCHMARK | FRAME: {i:04d}",
                (20, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 200),
                1,
                cv2.LINE_AA,
            )
            frames.append(img)
        return frames

    def start(self) -> bool:
        """Preload video frames into RAM ring buffer and activate source."""
        self._resolved_path = self._resolve_path()
        loaded_frames: List[np.ndarray] = []

        if self._resolved_path and os.path.isfile(self._resolved_path):
            cap = cv2.VideoCapture(self._resolved_path)
            if cap.isOpened():
                total_in_file = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                logger.info(
                    "Preloading up to %d frames into RAM from '%s' (%d total frames)...",
                    self._buffer_size,
                    self._resolved_path,
                    total_in_file,
                )
                t_load_start = time.monotonic()
                while len(loaded_frames) < self._buffer_size and (time.monotonic() - t_load_start < 2.0):
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        # Loop video to satisfy requested buffer size
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ret2, frame2 = cap.read()
                        if not ret2 or frame2 is None:
                            break
                        frame = frame2
                    h, w = frame.shape[:2]
                    if w > 640 or h > 640:
                        scale = min(640.0 / w, 640.0 / h)
                        frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
                    loaded_frames.append(frame.copy())
                cap.release()

        if not loaded_frames:
            logger.info(
                "No video file accessible at '%s'; generating %d procedural benchmark frames in RAM...",
                self._requested_path,
                self._buffer_size,
            )
            loaded_frames = self._generate_synthetic_frames(self._buffer_size)
            self._synthetic_mode = True
            self._source_id = "ring_buffer:synthetic"
        else:
            self._synthetic_mode = False
            base_name = os.path.basename(self._resolved_path or "video")
            self._source_id = f"ring_buffer:{base_name}"

        with self._lock:
            self._frames = loaded_frames
            self._current_idx = 0
            self._frame_seq = 0
            self._is_active = True
            self._fps_timestamps.clear()

        logger.info(
            "RingBufferVideoSource activated: %d frames preloaded in RAM (unthrottled=%s, source_id=%s)",
            len(self._frames),
            self._unthrottled,
            self._source_id,
        )
        return True

    def stop(self) -> None:
        """Release in-memory frame buffer and deactivate source."""
        with self._lock:
            self._is_active = False
            self._frames.clear()
            self._current_idx = 0
        logger.info("RingBufferVideoSource stopped cleanly")

    def get_frame(self, timeout: float = 0.5) -> Optional[VideoFrame]:
        """
        Deliver the next frame from circular buffer immediately with zero decode overhead.
        """
        with self._lock:
            if not self._is_active or not self._frames:
                return None

            now = time.monotonic()
            if not self._unthrottled and self._min_frame_interval > 0.0:
                elapsed = now - self._last_frame_time
                if elapsed < self._min_frame_interval:
                    time.sleep(self._min_frame_interval - elapsed)
                    now = time.monotonic()

            self._last_frame_time = now
            self._fps_timestamps.append(now)

            raw_frame = self._frames[self._current_idx]
            self._current_idx = (self._current_idx + 1) % len(self._frames)
            self._frame_seq += 1

            h, w = raw_frame.shape[:2]
            return VideoFrame(
                frame_seq=self._frame_seq,
                data=raw_frame,
                source_id=self._source_id,
                width=w,
                height=h,
                monotonic_ts=now,
            )

    def is_active(self) -> bool:
        return self._is_active and len(self._frames) > 0

    def set_unthrottled(self, unthrottled: bool) -> None:
        """Enable or disable unthrottled maximum-throughput feeding."""
        with self._lock:
            self._unthrottled = unthrottled
            self._min_frame_interval = (1.0 / self._target_fps) if not self._unthrottled else 0.0

    def get_feeder_fps(self) -> float:
        """Calculate instantaneous frame emission throughput in FPS."""
        with self._lock:
            if len(self._fps_timestamps) < 2:
                return 0.0
            duration = self._fps_timestamps[-1] - self._fps_timestamps[0]
            if duration <= 0:
                return 0.0
            return round((len(self._fps_timestamps) - 1) / duration, 1)

    def get_status(self) -> Dict[str, Any]:
        """Return status dictionary describing ring-buffer parameters and throughput."""
        with self._lock:
            return {
                "source_type": "ring_buffer",
                "source_id": self._source_id,
                "buffer_size": len(self._frames),
                "current_index": self._current_idx,
                "frames_emitted": self._frame_seq,
                "unthrottled": self._unthrottled,
                "feeder_fps": self.get_feeder_fps(),
                "synthetic_mode": self._synthetic_mode,
                "active": self._is_active,
                "file_path": self._resolved_path or self._requested_path,
            }
