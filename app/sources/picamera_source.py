"""
Raspberry Pi Camera Module (CSI) source via Picamera2 / libcamera.
"""

from __future__ import annotations

import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import numpy as np

from app.core.logging_config import get_logger
from app.sources.base import BaseVideoSource, VideoFrame

logger = get_logger("SOURCE.PICAMERA")


class PiCameraSource(BaseVideoSource):
    """Captures frames from Raspberry Pi Camera Module using Picamera2."""

    def __init__(
        self,
        camera_num: int = 0,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
    ):
        self._camera_num = camera_num
        self._width = width
        self._height = height
        self._fps = fps

        self._picam2: Any = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._frame_queue: queue.Queue[VideoFrame] = queue.Queue(maxsize=2)
        self._frame_seq = 0
        self._dropped_count = 0
        self._error_status: Optional[str] = None
        self._is_capturing = False

    def is_available(self) -> bool:
        """Check if Picamera2 library is importable on this system."""
        try:
            import picamera2  # type: ignore
            return True
        except ImportError:
            return False

    def start(self) -> bool:
        if not self.is_available():
            self._error_status = "Picamera2 is not installed or accessible in this environment. (Raspberry Pi OS with libcamera required. Run Native Deployment Option 1 on Raspberry Pi 5 for CSI camera)."
            logger.warning(self._error_status)
            return False

        try:
            from picamera2 import Picamera2  # type: ignore

            self._picam2 = Picamera2(camera_num=self._camera_num)
            config = self._picam2.create_preview_configuration(
                main={"format": "BGR888", "size": (self._width, self._height)},
                controls={"FrameRate": self._fps},
            )
            self._picam2.configure(config)
            self._picam2.start()

            self._stop_event.clear()
            self._is_capturing = True
            self._error_status = None
            self._thread = threading.Thread(
                target=self._capture_loop, name="PiCameraCapture", daemon=True
            )
            self._thread.start()
            logger.info("PiCamera source started (cam %d, %dx%d @ %dfps)", self._camera_num, self._width, self._height, self._fps)
            return True

        except Exception as e:
            self._error_status = f"Failed to start Picamera2: {e}"
            logger.error(self._error_status, exc_info=True)
            self._is_capturing = False
            return False

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

        if self._picam2:
            try:
                self._picam2.stop()
                self._picam2.close()
            except Exception as e:
                logger.warning("Error stopping Picamera2: %s", e)
            self._picam2 = None

        self._is_capturing = False
        logger.info("PiCamera source stopped")

    def _capture_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                arr = self._picam2.capture_array()
                if arr is None:
                    time.sleep(0.01)
                    continue

                self._frame_seq += 1
                frame = VideoFrame(
                    frame_seq=self._frame_seq,
                    data=arr,
                    source_id=f"picamera:{self._camera_num}",
                    width=self._width,
                    height=self._height,
                    monotonic_ts=time.monotonic(),
                )

                # Push freshest frame, drop oldest if full
                if self._frame_queue.full():
                    try:
                        self._frame_queue.get_nowait()
                        self._dropped_count += 1
                    except queue.Empty:
                        pass
                self._frame_queue.put_nowait(frame)

            except Exception as e:
                self._error_status = str(e)
                logger.error("PiCamera frame acquisition error: %s", e)
                time.sleep(0.1)

    def get_frame(self, timeout: float = 0.5) -> Optional[VideoFrame]:
        try:
            return self._frame_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def is_active(self) -> bool:
        return self._is_capturing and (self._thread is not None and self._thread.is_alive())

    def get_status(self) -> Dict[str, Any]:
        return {
            "source_type": "picamera",
            "camera_num": self._camera_num,
            "resolution": f"{self._width}x{self._height}",
            "requested_fps": self._fps,
            "active": self.is_active(),
            "frames_captured": self._frame_seq,
            "frames_dropped": self._dropped_count,
            "error_status": self._error_status,
        }
