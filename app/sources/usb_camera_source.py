"""
USB webcam source via OpenCV V4L2 backend with disconnect detection and recovery.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Dict, Optional, Union
import cv2
import numpy as np

from app.core.logging_config import get_logger
from app.sources.base import BaseVideoSource, VideoFrame

logger = get_logger("SOURCE.USB")


class USBCameraSource(BaseVideoSource):
    """Captures video from a V4L2 USB camera device."""

    def __init__(
        self,
        device: Union[str, int] = "/dev/video0",
        width: int = 640,
        height: int = 480,
        fps: int = 30,
    ):
        self._device = device
        self._width = width
        self._height = height
        self._fps = fps

        self._cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._frame_queue: queue.Queue[VideoFrame] = queue.Queue(maxsize=2)
        self._frame_seq = 0
        self._dropped_count = 0
        self._reconnect_count = 0
        self._error_status: Optional[str] = None
        self._is_capturing = False

    def _open_device(self) -> bool:
        dev_arg: Any = self._device
        # If integer index passed as string (e.g., "0"), convert to int
        if isinstance(self._device, str) and self._device.isdigit():
            dev_arg = int(self._device)

        cap = cv2.VideoCapture(dev_arg, cv2.CAP_V4L2)
        if not cap.isOpened():
            # Fall back to default backend if V4L2 fails
            cap = cv2.VideoCapture(dev_arg)

        if not cap.isOpened():
            self._error_status = f"Cannot open USB camera device: {self._device}"
            return False

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        cap.set(cv2.CAP_PROP_FPS, self._fps)

        self._cap = cap
        self._error_status = None
        return True

    def start(self) -> bool:
        if not self._open_device():
            logger.warning("Failed to open USB camera '%s'", self._device)
            return False

        self._stop_event.clear()
        self._is_capturing = True
        self._thread = threading.Thread(
            target=self._capture_loop, name="USBCameraCapture", daemon=True
        )
        self._thread.start()
        logger.info("USB camera source started (%s @ %dx%d)", self._device, self._width, self._height)
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
                logger.warning("Error releasing USB camera: %s", e)
            self._cap = None

        self._is_capturing = False
        logger.info("USB camera source stopped")

    def _capture_loop(self) -> None:
        consecutive_failures = 0
        while not self._stop_event.is_set():
            if self._cap is None or not self._cap.isOpened():
                # Attempt reconnect
                time.sleep(1.0)
                self._reconnect_count += 1
                if not self._open_device():
                    continue

            ret, frame = self._cap.read()
            if not ret or frame is None:
                consecutive_failures += 1
                if consecutive_failures > 10:
                    self._error_status = "Camera disconnected or frame read failed repeatedly"
                    logger.warning("USB camera read failed 10+ times, releasing handle")
                    if self._cap:
                        self._cap.release()
                        self._cap = None
                    time.sleep(1.0)
                time.sleep(0.02)
                continue

            consecutive_failures = 0
            self._frame_seq += 1
            h, w = frame.shape[:2]

            vframe = VideoFrame(
                frame_seq=self._frame_seq,
                data=frame,
                source_id=f"usb:{self._device}",
                width=w,
                height=h,
                monotonic_ts=time.monotonic(),
            )

            # Drop stale preview frames over allowing backlog to accumulate
            if self._frame_queue.full():
                try:
                    self._frame_queue.get_nowait()
                    self._dropped_count += 1
                except queue.Empty:
                    pass
            self._frame_queue.put_nowait(vframe)

    def get_frame(self, timeout: float = 0.5) -> Optional[VideoFrame]:
        try:
            return self._frame_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def is_active(self) -> bool:
        return self._is_capturing and (self._cap is not None and self._cap.isOpened())

    def get_status(self) -> Dict[str, Any]:
        return {
            "source_type": "usb",
            "device": str(self._device),
            "resolution": f"{self._width}x{self._height}",
            "requested_fps": self._fps,
            "active": self.is_active(),
            "frames_captured": self._frame_seq,
            "frames_dropped": self._dropped_count,
            "reconnect_count": self._reconnect_count,
            "error_status": self._error_status,
        }
