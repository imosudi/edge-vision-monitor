"""
Prerecorded video file playback source with playback controls, looping,
path-traversal protection, and procedural synthetic fallback for testing.
"""

from __future__ import annotations

import os
from pathlib import Path
import queue
import threading
import time
from typing import Any, Dict, Optional
import cv2
import numpy as np

from app.core.logging_config import get_logger
from app.sources.base import BaseVideoSource, VideoFrame

logger = get_logger("SOURCE.FILE")


class VideoFileSource(BaseVideoSource):
    """Plays prerecorded video files or generates synthetic frames for testing."""

    def __init__(
        self,
        file_path: Optional[str] = None,
        media_dir: str = "media",
        loop: bool = True,
        target_fps: int = 30,
    ):
        self._media_dir = os.path.abspath(media_dir)
        self._requested_path = file_path
        self._loop = loop
        self._target_fps = target_fps

        self._resolved_path: Optional[str] = None
        self._cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._frame_queue: queue.Queue[VideoFrame] = queue.Queue(maxsize=2)
        self._frame_seq = 0
        self._dropped_count = 0
        self._native_fps = float(target_fps)
        self._total_frames = 0
        self._current_frame_idx = 0
        self._synthetic_mode = False
        self._error_status: Optional[str] = None
        self._is_capturing = False

    def _resolve_and_validate_path(self) -> Optional[str]:
        if not self._requested_path:
            return None

        # Guard against path traversal
        abs_target = os.path.abspath(self._requested_path)
        # Check if inside media_dir or directly accessible
        if not abs_target.startswith(self._media_dir) and not os.path.exists(abs_target):
            # Attempt to look inside media_dir
            candidate = os.path.join(self._media_dir, os.path.basename(self._requested_path))
            if os.path.exists(candidate):
                abs_target = candidate

        if not os.path.exists(abs_target):
            return None

        # Verify extension
        ext = os.path.splitext(abs_target)[1].lower()
        if ext not in [".mp4", ".avi", ".mkv", ".mov", ".m4v"]:
            self._error_status = f"Unsupported video file format '{ext}'"
            return None

        return abs_target

    def start(self) -> bool:
        self._resolved_path = self._resolve_and_validate_path()

        if self._resolved_path and os.path.isfile(self._resolved_path):
            cap = cv2.VideoCapture(self._resolved_path)
            if cap.isOpened():
                self._cap = cap
                fps_val = cap.get(cv2.CAP_PROP_FPS)
                self._native_fps = fps_val if fps_val > 0 else float(self._target_fps)
                self._total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                self._synthetic_mode = False
                logger.info(
                    "Opened video file '%s' (%d frames @ %.1f fps)",
                    self._resolved_path,
                    self._total_frames,
                    self._native_fps,
                )
            else:
                logger.warning("Could not open video file '%s'; falling back to synthetic generator", self._resolved_path)
                self._synthetic_mode = True
        else:
            logger.info("Video file '%s' not found; using synthetic video generator", self._requested_path)
            self._synthetic_mode = True
            self._native_fps = float(self._target_fps)
            self._total_frames = 1000

        self._stop_event.clear()
        self._pause_event.clear()
        self._is_capturing = True
        self._thread = threading.Thread(
            target=self._playback_loop, name="VideoFilePlayback", daemon=True
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

        if self._cap:
            try:
                self._cap.release()
            except Exception as e:
                logger.warning("Error releasing video file: %s", e)
            self._cap = None

        self._is_capturing = False
        logger.info("Video file source stopped")

    def pause(self) -> None:
        self._pause_event.set()

    def resume(self) -> None:
        self._pause_event.clear()

    def restart(self) -> None:
        if self._cap and not self._synthetic_mode:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self._current_frame_idx = 0

    def _generate_synthetic_frame(self, frame_idx: int) -> np.ndarray:
        """Procedural synthetic edge video generator with moving geometric objects."""
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        # Background gradient
        t = frame_idx * 0.05
        bg_val = int(25 + 15 * np.sin(t * 0.5))
        img[:] = (bg_val, bg_val + 5, bg_val + 10)

        # Subtle grid lines
        for x in range(0, 640, 40):
            cv2.line(img, (x, 0), (x, 480), (35, 40, 50), 1)
        for y in range(0, 480, 40):
            cv2.line(img, (0, y), (640, y), (35, 40, 50), 1)

        # Moving object 1 (representing a car / box)
        x1 = int(320 + 200 * np.sin(t))
        y1 = int(240 + 80 * np.cos(t))
        cv2.rectangle(img, (x1 - 40, y1 - 25), (x1 + 40, y1 + 25), (45, 120, 240), -1)

        # Moving object 2 (representing a person / cylinder)
        x2 = int(250 + 120 * np.cos(t * 1.3))
        y2 = int(200 + 100 * np.sin(t * 1.3))
        cv2.circle(img, (x2, y2), 25, (80, 220, 100), -1)

        # Telemetry watermark on synthetic feed
        cv2.putText(
            img,
            f"SYNTHETIC DEMO FEED | FRAME: {frame_idx:05d}",
            (20, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 240, 255),
            1,
            cv2.LINE_AA,
        )
        return img

    def _playback_loop(self) -> None:
        frame_interval = 1.0 / max(1.0, self._native_fps)

        while not self._stop_event.is_set():
            if self._pause_event.is_set():
                time.sleep(0.05)
                continue

            t_frame_start = time.monotonic()

            if self._synthetic_mode:
                self._current_frame_idx += 1
                raw_frame = self._generate_synthetic_frame(self._current_frame_idx)
            else:
                if self._cap is None or not self._cap.isOpened():
                    time.sleep(0.1)
                    continue

                ret, raw_frame = self._cap.read()
                if not ret or raw_frame is None:
                    if self._loop:
                        self.restart()
                        continue
                    else:
                        logger.info("Video playback completed (end of file reached)")
                        break
                self._current_frame_idx += 1

            self._frame_seq += 1
            h, w = raw_frame.shape[:2]

            vframe = VideoFrame(
                frame_seq=self._frame_seq,
                data=raw_frame,
                source_id="file:synthetic" if self._synthetic_mode else f"file:{os.path.basename(self._resolved_path or '')}",
                width=w,
                height=h,
                monotonic_ts=time.monotonic(),
            )

            # Drop stale if queue full
            if self._frame_queue.full():
                try:
                    self._frame_queue.get_nowait()
                    self._dropped_count += 1
                except queue.Empty:
                    pass
            self._frame_queue.put_nowait(vframe)

            # Pacing sleep to respect video native FPS
            elapsed = time.monotonic() - t_frame_start
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def get_frame(self, timeout: float = 0.5) -> Optional[VideoFrame]:
        try:
            return self._frame_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def is_active(self) -> bool:
        return self._is_capturing and (self._thread is not None and self._thread.is_alive())

    def get_status(self) -> Dict[str, Any]:
        return {
            "source_type": "file",
            "file_path": self._resolved_path or self._requested_path,
            "synthetic_mode": self._synthetic_mode,
            "native_fps": round(self._native_fps, 1),
            "total_frames": self._total_frames,
            "current_frame": self._current_frame_idx,
            "is_paused": self._pause_event.is_set(),
            "active": self.is_active(),
            "frames_captured": self._frame_seq,
            "frames_dropped": self._dropped_count,
            "error_status": self._error_status,
        }
