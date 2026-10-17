"""
Integration tests for VideoSourceManager switching and frame acquisition.
"""

import time
from app.core.config import VideoSourceConfig
from app.sources.manager import VideoSourceManager


def test_video_source_manager_synthetic_fallback(temp_dir):
    cfg = VideoSourceConfig(
        default_source_type="file",
        media_dir=temp_dir,
        video_file_path=None,  # triggers synthetic procedural generator
    )
    mgr = VideoSourceManager(cfg)
    started = mgr.start_default_source()
    assert started is True

    # Pull a frame
    time.sleep(0.1)
    frame = mgr.get_frame(timeout=1.0)
    assert frame is not None
    assert frame.data.shape == (480, 640, 3)
    assert frame.frame_seq >= 1

    status = mgr.get_status()
    assert status["is_active"] is True
    assert status["active_type"] == "file"

    mgr.stop()
    assert mgr.get_status()["is_active"] is False


def test_video_source_manager_browser_camera(temp_dir):
    import cv2
    import numpy as np

    cfg = VideoSourceConfig(
        default_source_type="file",
        media_dir=temp_dir,
    )
    mgr = VideoSourceManager(cfg)

    # 1. Enumerate sources includes browser_camera_supported
    catalog = mgr.enumerate_sources()
    assert catalog.get("browser_camera_supported") is True

    # 2. Switch to browser source
    switched = mgr.switch_source("browser", width=640, height=480)
    assert switched is True
    status = mgr.get_status()
    assert status["active_type"] == "browser"
    assert status["is_active"] is True

    # 3. Simulate pushing a JPEG frame from client browser
    dummy_img = np.zeros((480, 640, 3), dtype=np.uint8)
    dummy_img[:] = (0, 255, 0)
    _, encoded_jpg = cv2.imencode(".jpg", dummy_img)

    pushed = mgr.push_browser_frame(encoded_jpg.tobytes())
    assert pushed is True

    # 4. Ingest pushed frame
    frame = mgr.get_frame(timeout=1.0)
    assert frame is not None
    assert frame.data.shape == (480, 640, 3)
    assert frame.source_id == "browser:client"
    assert frame.frame_seq >= 1

    mgr.stop()
    assert mgr.get_status()["is_active"] is False
