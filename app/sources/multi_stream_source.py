"""
Multi-Stream Concurrent Ingestion Feeder designed for sustained NPU saturation
and thermal characterisation (Workload B).
Simulates concurrent multi-camera video streams feeding into the shared inference pipeline.
"""

from __future__ import annotations

import collections
import glob
import os
import queue
import threading
import time
from typing import Any, Deque, Dict, List, Optional
import cv2
import numpy as np

from app.core.logging_config import get_logger
from app.sources.base import BaseVideoSource, VideoFrame

logger = get_logger("SOURCE.MULTI_STREAM")


class MultiStreamSource(BaseVideoSource):
    """
    Concurrent multi-stream ingestion feeder interleaving frames from multiple video feeds
    to maximise accelerator duty cycle, compute utilisation, and thermal dissipation (Workload B).
    """

    def __init__(
        self,
        stream_count: int = 4,
        file_paths: Optional[List[str]] = None,
        media_dir: str = "media",
        buffer_size_per_stream: int = 60,
        queue_size: int = 64,
        unthrottled: bool = True,
    ):
        self._stream_count = max(1, min(16, stream_count))
        self._file_paths = file_paths or []
        self._media_dir = os.path.abspath(media_dir)
        self._buffer_size_per_stream = max(10, buffer_size_per_stream)
        self._queue_size = max(16, queue_size)
        self._unthrottled = unthrottled

        self._frame_queue: queue.Queue[VideoFrame] = queue.Queue(maxsize=self._queue_size)
        self._stream_buffers: List[List[np.ndarray]] = []
        self._stream_indices: List[int] = []
        self._stream_counters: List[int] = []
        self._stream_names: List[str] = []

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_active = False
        self._total_emitted = 0
        self._dropped_count = 0
        self._fps_timestamps: Deque[float] = collections.deque(maxlen=100)
        self._lock = threading.RLock()

    def _discover_candidate_files(self) -> List[str]:
        candidates: List[str] = []
        for p in self._file_paths:
            if not p:
                continue
            abs_p = os.path.abspath(p)
            if os.path.exists(abs_p):
                candidates.append(abs_p)
                continue
            media_p = os.path.join(self._media_dir, os.path.basename(p))
            if os.path.exists(media_p):
                candidates.append(media_p)
                continue
            media_rel = os.path.join(self._media_dir, p)
            if os.path.exists(media_rel):
                candidates.append(media_rel)
                continue

        if not candidates and os.path.isdir(self._media_dir):
            for ext in ("*.mp4", "*.avi", "*.mkv", "*.mov", "*.m4v"):
                for fpath in glob.glob(os.path.join(self._media_dir, ext)):
                    candidates.append(fpath)
        return candidates

    def _generate_synthetic_stream(self, stream_idx: int, count: int) -> List[np.ndarray]:
        """Generate distinct synthetic video frames per stream for visual separation."""
        frames: List[np.ndarray] = []
        hue_offset = (stream_idx * 55) % 180
        for i in range(count):
            img = np.zeros((480, 640, 3), dtype=np.uint8)
            t = (i * 0.08) + (stream_idx * 1.5)
            bg = int(20 + 10 * np.sin(t * 0.4))
            img[:] = (bg, bg + (stream_idx * 5), bg + 12)

            # Camera name overlay banner
            cv2.rectangle(img, (0, 0), (640, 45), (30, 35, 45), -1)
            cv2.putText(
                img,
                f"STREAM CHANNEL {stream_idx} (CAM_{stream_idx:02d}) | FRAME: {i:04d}",
                (15, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 220, 255),
                2,
                cv2.LINE_AA,
            )

            # Procedural moving objects with different trajectories per stream
            x1 = int(320 + 210 * np.sin(t * (1.0 + stream_idx * 0.15)))
            y1 = int(250 + 110 * np.cos(t * (0.9 + stream_idx * 0.1)))
            b_col = int(80 + (stream_idx * 40)) % 255
            g_col = int(120 + (stream_idx * 30)) % 255
            r_col = int(200 - (stream_idx * 35)) % 255
            cv2.rectangle(img, (x1 - 45, y1 - 30), (x1 + 45, y1 + 30), (b_col, g_col, r_col), -1)

            x2 = int(280 + 150 * np.cos(t * 1.3))
            y2 = int(220 + 90 * np.sin(t * 1.3))
            cv2.circle(img, (x2, y2), 25, (50, 240, 120), -1)

            frames.append(img)
        return frames

    def start(self) -> bool:
        """Preload and initialise multi-stream buffers and start background ingestion."""
        candidate_files = self._discover_candidate_files()
        self._stream_buffers.clear()
        self._stream_indices.clear()
        self._stream_counters.clear()
        self._stream_names.clear()

        for s_idx in range(self._stream_count):
            stream_name = f"stream_{s_idx}"
            self._stream_names.append(stream_name)
            self._stream_indices.append(0)
            self._stream_counters.append(0)

            loaded: List[np.ndarray] = []
            if candidate_files:
                fpath = candidate_files[s_idx % len(candidate_files)]
                cap = cv2.VideoCapture(fpath)
                if cap.isOpened():
                    t_load = time.monotonic()
                    while len(loaded) < self._buffer_size_per_stream and (time.monotonic() - t_load < 1.0):
                        ret, f = cap.read()
                        if not ret or f is None:
                            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                            ret2, f2 = cap.read()
                            if not ret2 or f2 is None:
                                break
                            f = f2
                        h, w = f.shape[:2]
                        if w > 640 or h > 640:
                            scale = min(640.0 / w, 640.0 / h)
                            f = cv2.resize(f, (int(w * scale), int(h * scale)))
                        loaded.append(f.copy())
                    cap.release()

            if not loaded:
                loaded = self._generate_synthetic_stream(s_idx, self._buffer_size_per_stream)

            self._stream_buffers.append(loaded)

        # Clear queue and start ingestion thread
        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                break

        self._stop_event.clear()
        self._is_active = True
        self._thread = threading.Thread(
            target=self._feeder_loop,
            name="MultiStreamFeederWorker",
            daemon=True,
        )
        self._thread.start()

        logger.info(
            "MultiStreamSource started: %d concurrent streams (%d frames per stream preloaded)",
            self._stream_count,
            self._buffer_size_per_stream,
        )
        return True

    def stop(self) -> None:
        """Stop background ingestion thread and clear frame queue."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self._is_active = False

        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                break

        self._stream_buffers.clear()
        logger.info("MultiStreamSource stopped cleanly")

    def _feeder_loop(self) -> None:
        """Round-robin ingestion loop continuously topping up the frame queue."""
        curr_stream = 0

        while not self._stop_event.is_set():
            if self._frame_queue.full():
                time.sleep(0.002)
                continue

            buf = self._stream_buffers[curr_stream]
            idx = self._stream_indices[curr_stream]
            self._stream_indices[curr_stream] = (idx + 1) % len(buf)
            self._stream_counters[curr_stream] += 1
            raw_frame = buf[idx]

            h, w = raw_frame.shape[:2]
            vframe = VideoFrame(
                frame_seq=self._stream_counters[curr_stream],
                data=raw_frame,
                source_id=self._stream_names[curr_stream],
                width=w,
                height=h,
                monotonic_ts=time.monotonic(),
            )

            try:
                self._frame_queue.put(vframe, timeout=0.05)
            except queue.Full:
                self._dropped_count += 1

            curr_stream = (curr_stream + 1) % self._stream_count

    def get_frame(self, timeout: float = 0.5) -> Optional[VideoFrame]:
        """Retrieve next frame across interleaved concurrent streams."""
        try:
            frame = self._frame_queue.get(timeout=timeout)
            now = time.monotonic()
            self._fps_timestamps.append(now)
            self._total_emitted += 1
            return frame
        except queue.Empty:
            return None

    def is_active(self) -> bool:
        return self._is_active and (self._thread is not None and self._thread.is_alive())

    def get_feeder_fps(self) -> float:
        """Calculate aggregate throughput across all active streams."""
        if len(self._fps_timestamps) < 2:
            return 0.0
        duration = self._fps_timestamps[-1] - self._fps_timestamps[0]
        if duration <= 0:
            return 0.0
        return round((len(self._fps_timestamps) - 1) / duration, 1)

    def get_status(self) -> Dict[str, Any]:
        """Return status dictionary describing active streams and queue metrics."""
        frames_map = {}
        for i, name in enumerate(self._stream_names):
            frames_map[name] = self._stream_counters[i] if i < len(self._stream_counters) else 0

        return {
            "source_type": "multi_stream",
            "stream_count": self._stream_count,
            "active": self.is_active(),
            "queue_depth": self._frame_queue.qsize(),
            "max_queue_size": self._queue_size,
            "total_frames_emitted": self._total_emitted,
            "dropped_frames": self._dropped_count,
            "feeder_fps": self.get_feeder_fps(),
            "unthrottled": self._unthrottled,
            "frames_per_stream": frames_map,
        }
