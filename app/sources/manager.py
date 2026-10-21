"""
Video Source Manager: thread-safe lifecycle control, dynamic source enumeration,
controlled switching, and frame buffering.
"""

from __future__ import annotations

import glob
import os
import threading
from typing import Any, Dict, List, Optional

from app.core.config import VideoSourceConfig
from app.core.ipc import publish_source_status
from app.core.logging_config import get_logger
from app.sources.base import BaseVideoSource, VideoFrame
from app.sources.browser_source import BrowserCameraSource
from app.sources.multi_stream_source import MultiStreamSource
from app.sources.picamera_source import PiCameraSource
from app.sources.ring_buffer_source import RingBufferVideoSource
from app.sources.usb_camera_source import USBCameraSource
from app.sources.video_file_source import VideoFileSource

logger = get_logger("SOURCE.MANAGER")


class VideoSourceManager:
    """Coordinates video input sources, enforces single-owner hardware locking,"""

    def __init__(self, config: VideoSourceConfig):
        self._config = config
        self._lock = threading.RLock()
        self._active_source: Optional[BaseVideoSource] = None
        self._active_type: str = "none"
        self._source_id: str = "none"
        self._last_error: Optional[str] = None

    def enumerate_sources(self) -> Dict[str, Any]:
        """Discover available video sources across CSI, USB, browser, and media directories."""
        # 1. Check Pi Camera CSI availability
        csi_available = False
        try:
            import picamera2  # type: ignore
            csi_available = True
        except ImportError:
            pass

        # 2. Check USB V4L2 devices
        usb_devices = []
        for dev_path in sorted(glob.glob("/dev/video*")):
            # Filter device paths
            usb_devices.append(dev_path)

        # 3. Check Media Files
        media_files = []
        if os.path.isdir(self._config.media_dir):
            for ext in ("*.mp4", "*.avi", "*.mkv", "*.mov", "*.m4v"):
                for fpath in glob.glob(os.path.join(self._config.media_dir, ext)):
                    media_files.append(os.path.basename(fpath))

        return {
            "csi_camera_supported": csi_available,
            "browser_camera_supported": True,
            "ring_buffer_supported": True,
            "multi_stream_supported": True,
            "usb_devices": usb_devices,
            "media_files": sorted(media_files),
            "current_source_type": self._active_type,
            "current_source_id": self._source_id,
        }

    def start_default_source(self) -> bool:
        """Start the source configured in VideoSourceConfig."""
        target_type = self._config.default_source_type
        if target_type == "picamera":
            res = self.switch_source(
                "picamera",
                camera_num=self._config.picamera_camera_num,
                width=self._config.capture_width,
                height=self._config.capture_height,
                fps=self._config.capture_fps,
            )
            if res:
                return True
            logger.warning("Default source 'picamera' could not be started; falling back to video file source...")
            target_type = "file"

        if target_type == "usb":
            res = self.switch_source(
                "usb",
                device=self._config.usb_device_path,
                width=self._config.capture_width,
                height=self._config.capture_height,
                fps=self._config.capture_fps,
            )
            if res:
                return True
            logger.warning("Default source 'usb' could not be started; falling back to video file source...")
            target_type = "file"

        # Auto-discover video file if default path does not exist
        fpath = self._config.video_file_path
        if not fpath or not os.path.exists(fpath):
            discovered = self.enumerate_sources().get("media_files", [])
            if discovered:
                fpath = os.path.join(self._config.media_dir, discovered[0])

        return self.switch_source(
            "file",
            file_path=fpath,
            loop=self._config.loop_playback,
            target_fps=self._config.capture_fps,
        )

    def switch_source(self, source_type: str, **kwargs) -> bool:
        """
        Thread-safe controlled transition from current source to new source.
        Releases old camera handle before opening new one.
        """
        with self._lock:
            logger.info("Transitioning video source from '%s' to '%s'...", self._active_type, source_type)

            # 1. Stop current source cleanly
            if self._active_source:
                try:
                    self._active_source.stop()
                except Exception as e:
                    logger.warning("Error stopping previous video source: %s", e)
                self._active_source = None

            # 2. Instantiate new source
            new_source: Optional[BaseVideoSource] = None
            new_id = source_type

            try:
                if source_type == "picamera":
                    cam_num = kwargs.get("camera_num", self._config.picamera_camera_num)
                    w = kwargs.get("width", self._config.capture_width)
                    h = kwargs.get("height", self._config.capture_height)
                    fps = kwargs.get("fps", self._config.capture_fps)
                    new_source = PiCameraSource(camera_num=cam_num, width=w, height=h, fps=fps)
                    new_id = f"picamera:{cam_num}"

                elif source_type == "usb":
                    dev = kwargs.get("device", self._config.usb_device_path)
                    w = kwargs.get("width", self._config.capture_width)
                    h = kwargs.get("height", self._config.capture_height)
                    fps = kwargs.get("fps", self._config.capture_fps)
                    new_source = USBCameraSource(device=dev, width=w, height=h, fps=fps)
                    new_id = f"usb:{dev}"

                elif source_type == "file":
                    fpath = kwargs.get("file_path", self._config.video_file_path)
                    loop = kwargs.get("loop", self._config.loop_playback)
                    fps = kwargs.get("fps", self._config.capture_fps)
                    new_source = VideoFileSource(
                        file_path=fpath,
                        media_dir=self._config.media_dir,
                        loop=loop,
                        target_fps=fps,
                    )
                    new_id = f"file:{os.path.basename(fpath or 'synthetic')}"

                elif source_type in ("browser", "client"):
                    w = kwargs.get("width", self._config.capture_width)
                    h = kwargs.get("height", self._config.capture_height)
                    fps = kwargs.get("fps", self._config.capture_fps)
                    new_source = BrowserCameraSource(width=w, height=h, fps=fps)
                    new_id = "browser:client"

                elif source_type in ("ring_buffer", "benchmark_ring_buffer", "workload_a"):
                    fpath = kwargs.get("file_path", self._config.video_file_path)
                    if not fpath or not os.path.exists(fpath):
                        discovered = self.enumerate_sources().get("media_files", [])
                        if discovered:
                            fpath = os.path.join(self._config.media_dir, discovered[0])
                    buf_size = kwargs.get("buffer_size", 120)
                    unthrottled = kwargs.get("unthrottled", True)
                    target_fps = kwargs.get("fps", self._config.capture_fps)
                    new_source = RingBufferVideoSource(
                        file_path=fpath,
                        media_dir=self._config.media_dir,
                        buffer_size=buf_size,
                        unthrottled=unthrottled,
                        target_fps=target_fps,
                    )
                    base_name = os.path.basename(fpath or "synthetic")
                    new_id = f"ring_buffer:{base_name}"

                elif source_type in ("multi_stream", "workload_b"):
                    streams = kwargs.get("stream_count", 4)
                    paths = kwargs.get("file_paths", None)
                    buf_size = kwargs.get("buffer_size_per_stream", 60)
                    q_size = kwargs.get("queue_size", 64)
                    unthrottled = kwargs.get("unthrottled", True)
                    new_source = MultiStreamSource(
                        stream_count=streams,
                        file_paths=paths,
                        media_dir=self._config.media_dir,
                        buffer_size_per_stream=buf_size,
                        queue_size=q_size,
                        unthrottled=unthrottled,
                    )
                    new_id = f"multi_stream:{streams}_channels"

                else:
                    logger.error("Unknown video source type: %s", source_type)
                    return False

                # 3. Start new source
                if new_source and new_source.start():
                    self._active_source = new_source
                    self._active_type = source_type
                    self._source_id = new_id
                    self._last_error = None
                    logger.info("Successfully switched video source to '%s'", self._source_id)
                    publish_source_status(self.get_status(), self.enumerate_sources())
                    return True
                else:
                    err_msg = getattr(new_source, "_error_status", None)
                    if not err_msg:
                        if source_type == "picamera":
                            err_msg = "Picamera2 is not installed or accessible in this environment. Ensure libcamera, python3-picamera2, and Raspberry Pi camera device mappings (/dev, /run/udev, /sys) are present."
                        else:
                            err_msg = f"Failed to start new video source '{source_type}'"
                    self._last_error = err_msg
                    logger.error("Failed to start new video source '%s': %s", source_type, err_msg)

                    # If camera fails, fallback to video file or synthetic to prevent service deadlock
                    if source_type != "file":
                        logger.info("Attempting automatic fallback to video file or synthetic source...")
                        discovered = self.enumerate_sources().get("media_files", [])
                        fallback_path = os.path.join(self._config.media_dir, discovered[0]) if discovered else None
                        fallback = VideoFileSource(
                            file_path=fallback_path,
                            media_dir=self._config.media_dir,
                            loop=True,
                            target_fps=30,
                        )
                        if fallback.start():
                            self._active_source = fallback
                            self._active_type = "file"
                            self._source_id = f"file:{os.path.basename(fallback_path or 'synthetic_fallback')}"
                            publish_source_status(self.get_status(), self.enumerate_sources())
                    return False

            except Exception as e:
                logger.error("Exception during video source switch: %s", e, exc_info=True)
                return False

    def get_frame(self, timeout: float = 0.5) -> Optional[VideoFrame]:
        """Retrieve latest frame from currently active source."""
        if self._active_source:
            return self._active_source.get_frame(timeout=timeout)
        return None

    def pause_playback(self) -> bool:
        """Pause video file playback if active source supports it."""
        if isinstance(self._active_source, VideoFileSource):
            self._active_source.pause()
            return True
        return False

    def resume_playback(self) -> bool:
        """Resume video file playback if active source supports it."""
        if isinstance(self._active_source, VideoFileSource):
            self._active_source.resume()
            return True
        return False

    def restart_playback(self) -> bool:
        """Restart video file playback to beginning."""
        if isinstance(self._active_source, VideoFileSource):
            self._active_source.restart()
            return True
        return False

    def stop(self) -> None:
        """Stop and release active source."""
        with self._lock:
            if self._active_source:
                try:
                    self._active_source.stop()
                except Exception as e:
                    logger.warning("Error stopping source in manager: %s", e)
                self._active_source = None
            self._active_type = "none"
            self._source_id = "none"

    def get_status(self) -> Dict[str, Any]:
        """Return status dictionary of active source."""
        status = {
            "active_type": self._active_type,
            "source_id": self._source_id,
            "is_active": self._active_source.is_active() if self._active_source else False,
            "error_status": getattr(self, "_last_error", None),
        }
        if self._active_source:
            status["source_details"] = self._active_source.get_status()
        return status

    def push_browser_frame(self, frame_data: Union[bytes, bytearray, np.ndarray]) -> bool:
        """Push a real-time frame captured from client web browser into active source."""
        with self._lock:
            if not isinstance(self._active_source, BrowserCameraSource):
                self.switch_source("browser")
            if isinstance(self._active_source, BrowserCameraSource):
                return self._active_source.push_frame(frame_data)
            return False

    def start_ring_buffer_source(
        self,
        file_path: Optional[str] = None,
        buffer_size: int = 120,
        unthrottled: bool = True,
    ) -> bool:
        """Switch to high-throughput unthrottled ring-buffer source for Workload A benchmarking."""
        return self.switch_source(
            "ring_buffer",
            file_path=file_path,
            buffer_size=buffer_size,
            unthrottled=unthrottled,
        )

    def start_multi_stream_source(
        self,
        stream_count: int = 4,
        file_paths: Optional[List[str]] = None,
        buffer_size_per_stream: int = 60,
        unthrottled: bool = True,
    ) -> bool:
        """Switch to concurrent multi-stream ingestion feeder for Workload B thermal characterisation."""
        return self.switch_source(
            "multi_stream",
            stream_count=stream_count,
            file_paths=file_paths,
            buffer_size_per_stream=buffer_size_per_stream,
            unthrottled=unthrottled,
        )

    def set_unthrottled(self, unthrottled: bool) -> bool:
        """Dynamically toggle unthrottled maximum-rate delivery if active source supports it."""
        with self._lock:
            if isinstance(self._active_source, RingBufferVideoSource):
                self._active_source.set_unthrottled(unthrottled)
                return True
            return False
