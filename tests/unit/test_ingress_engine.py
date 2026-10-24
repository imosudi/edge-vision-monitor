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


def test_multi_stream_source_high_concurrency(temp_dir):
    for streams in (12, 16, 20):
        source = MultiStreamSource(
            stream_count=streams,
            media_dir=temp_dir,
            buffer_size_per_stream=10,
            queue_size=32,
            unthrottled=True,
        )
        assert source.start() is True
        assert source.get_status()["stream_count"] == streams
        source.stop()


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


def test_tensor_cache_ring_buffer_and_multi_stream(temp_dir):
    """Verify that VideoFrames from ring buffer and multi-stream carry precomputed model tensors."""
    # 1. Ring Buffer
    ring = RingBufferVideoSource(media_dir=temp_dir, buffer_size=10, unthrottled=True)
    assert ring.start() is True
    f_ring = ring.get_frame(timeout=0.2)
    assert f_ring is not None
    assert f_ring.preprocessed_tensor is not None
    assert f_ring.preprocessed_tensor.shape == (1, 640, 640, 3)
    assert f_ring.scale is not None
    assert f_ring.pads is not None
    ring.stop()

    # 2. Multi-Stream Source
    multi = MultiStreamSource(stream_count=2, media_dir=temp_dir, buffer_size_per_stream=10, queue_size=16)
    assert multi.start() is True
    f_multi = multi.get_frame(timeout=0.3)
    assert f_multi is not None
    assert f_multi.preprocessed_tensor is not None
    assert f_multi.preprocessed_tensor.shape == (1, 640, 640, 3)
    assert f_multi.scale is not None
    assert f_multi.pads is not None
    multi.stop()


def test_inference_engine_tensor_cache_and_flush():
    """Verify inference engine handles cached tensors with zero prep latency and flush()."""
    from app.core.config import ModelConfig
    from app.inference.engine import MockInferenceEngine

    engine = MockInferenceEngine(ModelConfig())
    engine.initialize()

    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    # Standard path: preprocessing latency simulated
    res_std = engine.infer(dummy_frame, frame_seq=1, source_id="test")
    assert res_std is not None
    assert res_std.preprocessing_ms > 0.0

    # Cached tensor path: preprocessing latency eliminated (0.0 ms)
    cached_tensor = np.zeros((1, 640, 640, 3), dtype=np.uint8)
    res_cached = engine.infer(
        dummy_frame,
        frame_seq=2,
        source_id="test",
        preprocessed_tensor=cached_tensor,
        scale=1.0,
        pads=(0, 0),
    )
    assert res_cached is not None
    assert res_cached.preprocessing_ms == 0.0

    # Verify flush interface
    flushed = engine.flush()
    assert isinstance(flushed, list)
    engine.close()


def test_inference_service_benchmark_mode_tensor_cache(temp_dir):
    """Verify InferenceService achieves 0.0 ms preprocessing with cached tensors in benchmark mode."""
    from app.core.config import ModelConfig
    from app.inference.engine import MockInferenceEngine
    from app.services.inference_service import InferenceService

    source = RingBufferVideoSource(media_dir=temp_dir, buffer_size=15, unthrottled=True)
    source.start()

    engine = MockInferenceEngine(ModelConfig())
    engine.initialize()

    svc = InferenceService(engine=engine, source_manager=source)
    svc.set_benchmark_mode(True)
    assert svc.start() is True

    time.sleep(0.15)  # Allow worker to process several cached frames

    stats = svc.get_stats()
    assert stats["benchmark_mode"] is True
    assert stats["total_frames_processed"] > 0
    # Rolling preprocessing latency must be 0.0 ms because cached tensors were consumed
    prep_stats = stats["latencies"]["preprocessing_ms"]
    assert prep_stats["mean"] == 0.0

    svc.stop()
    source.stop()


