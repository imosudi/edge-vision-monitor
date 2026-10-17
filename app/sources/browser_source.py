"""
Browser and client device camera source.
Receives real-time frames captured directly on the client web browser device (via WebRTC getUserMedia)
and buffers them for accelerated YOLO11 neural inference.
"""

from __future__ import annotations

import queue
import time
from typing import Any, Dict, Optional, Union
import cv2
import numpy as np

from app.core.logging_config import get_logger
from app.sources.base import BaseVideoSource, VideoFrame

logger = get_logger("SOURCE.BROWSER")


class BrowserCameraSource(BaseVideoSource):
    """
    Video capture source ingesting frames streamed from the client web browser device.
    Enables clients on laptops, workstations, or mobile devices to process their local camera hardware.
    """

    def __init__(self, width: int = 640, height: int = 480, fps: int = 30):
        self._width = width
        self._height = height
        self._fps = fps

        self._frame_queue: queue.Queue[VideoFrame] = queue.Queue(maxsize=2)
        self._frame_seq = 0
        self._dropped_count = 0
        self._is_active = False
        self._error_status: Optional[str] = None
        self._last_frame_ts = 0.0

    def start(self) -> bool:
        self._is_active = True
        self._error_status = None
        self._last_frame_ts = time.monotonic()
        logger.info("Browser camera source initialised (awaiting client video stream)")
        return True

    def stop(self) -> None:
        self._is_active = False
        # Drain frame queue
        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                break
        logger.info("Browser camera source stopped")

    def push_frame(
        self,
        frame_input: Union[bytes, bytearray, np.ndarray],
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> bool:
        """
        Ingest a frame received from the web browser client (JPEG byte buffer or BGR ndarray).
        """
        if not self._is_active:
            self._is_active = True

        try:
            if isinstance(frame_input, (bytes, bytearray)):
                nparr = np.frombuffer(frame_input, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if img is None:
                    return False
            elif isinstance(frame_input, np.ndarray):
                img = frame_input
            else:
                return False

            h, w = img.shape[:2]
            self._width = w
            self._height = h
            self._frame_seq += 1
            self._last_frame_ts = time.monotonic()

            vframe = VideoFrame(
                frame_seq=self._frame_seq,
                data=img,
                source_id="browser:client",
                width=w,
                height=h,
                monotonic_ts=self._last_frame_ts,
            )

            if self._frame_queue.full():
                try:
                    self._frame_queue.get_nowait()
                    self._dropped_count += 1
                except queue.Empty:
                    pass

            self._frame_queue.put_nowait(vframe)
            return True

        except Exception as e:
            logger.debug("Error processing client browser frame: %s", e)
            return False

    def get_frame(self, timeout: float = 0.5) -> Optional[VideoFrame]:
        try:
            return self._frame_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def is_active(self) -> bool:
        return self._is_active

    def get_status(self) -> Dict[str, Any]:
        return {
            "source_type": "browser",
            "resolution": f"{self._width}x{self._height}",
            "requested_fps": self._fps,
            "active": self.is_active(),
            "frames_captured": self._frame_seq,
            "frames_dropped": self._dropped_count,
            "error_status": self._error_status,
        }
