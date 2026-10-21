"""
Unit tests for the Phase 2 Ingress Engine:
RingBufferVideoSource (Workload A) and MultiStreamSource (Workload B).
"""

import time
import pytest
import numpy as np

from app.core.config import VideoSourceConfig
from app.sources.manager import VideoSourceManager
from app.sources.multi_stream_source import MultiStreamSource
from app.sources.ring_buffer_source import RingBufferVideoSource


def test_ring_buffer_source_synthetic(temp_dir):
    source = RingBufferVideoSource(
        file_path=None,
        media_dir=temp_dir,
        buffer_size=20,
        unthrottled=True,
    )
    assert source.start() is True
    assert source.is_active() is True

    status = source.get_status()
    assert status["source_type"] == "ring_buffer"
    assert status["buffer_size"] == 20
    assert status["synthetic_mode"] is True
    assert status["unthrottled"] is True

    # Pull frames and verify rapid unthrottled retrieval
    t0 = time.monotonic()
    frames = []
    for _ in range(45):  # Pull more than buffer_size to verify circular wrapping
        f = source.get_frame(timeout=0.1)
        assert f is not None
        assert f.data.shape == (480, 640, 3)
        frames.append(f)

    elapsed = time.monotonic() - t0
    # 45 pre-decoded in-memory frames should be delivered in well under 0.5s
    assert elapsed < 0.5
    assert len(frames) == 45
    assert frames[-1].frame_seq == 45

    # Check status updates
    updated_status = source.get_status()
    assert updated_status["frames_emitted"] == 45

    source.stop()
    assert source.is_active() is False


def test_multi_stream_source_concurrency(temp_dir):
    source = MultiStreamSource(
        stream_count=4,
        media_dir=temp_dir,
        buffer_size_per_stream=15,
        queue_size=32,
        unthrottled=True,
    )
    assert source.start() is True
    assert source.is_active() is True

    time.sleep(0.05)  # Allow background feeder to populate initial queue

    # Pull frames and verify interleaved stream IDs
    observed_streams = set()
    for _ in range(20):
        f = source.get_frame(timeout=0.2)
        assert f is not None
        assert f.data.shape == (480, 640, 3)
        observed_streams.add(f.source_id)

    # All 4 channels should have contributed frames
    assert "stream_0" in observed_streams
    assert "stream_1" in observed_streams
    assert "stream_2" in observed_streams
    assert "stream_3" in observed_streams

    status = source.get_status()
    assert status["source_type"] == "multi_stream"
    assert status["stream_count"] == 4
    assert status["total_frames_emitted"] >= 20
    assert len(status["frames_per_stream"]) == 4

    source.stop()
    assert source.is_active() is False


def test_video_source_manager_workload_switching(temp_dir):
    cfg = VideoSourceConfig(
        default_source_type="file",
        media_dir=temp_dir,
    )
    mgr = VideoSourceManager(cfg)

    # Verify enumeration includes new ingress capabilities
    catalog = mgr.enumerate_sources()
    assert catalog.get("ring_buffer_supported") is True
    assert catalog.get("multi_stream_supported") is True

    # 1. Start Workload A (Ring Buffer)
    started_a = mgr.start_ring_buffer_source(buffer_size=25, unthrottled=True)
    assert started_a is True
    st_a = mgr.get_status()
    assert st_a["active_type"] == "ring_buffer"
    assert st_a["is_active"] is True

    frame_a = mgr.get_frame(timeout=0.5)
    assert frame_a is not None
    assert frame_a.data.shape == (480, 640, 3)

    # 2. Switch directly to Workload B (Multi-Stream)
    started_b = mgr.start_multi_stream_source(stream_count=3, buffer_size_per_stream=10)
    assert started_b is True
    st_b = mgr.get_status()
    assert st_b["active_type"] == "multi_stream"
    assert st_b["is_active"] is True

    frame_b = mgr.get_frame(timeout=0.5)
    assert frame_b is not None
    assert "stream_" in frame_b.source_id

    mgr.stop()
    assert mgr.get_status()["is_active"] is False

