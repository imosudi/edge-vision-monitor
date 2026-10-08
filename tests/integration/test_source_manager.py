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
