"""
Unit tests for SQLite database schema, WAL mode, batched writes, downsampling,
automated retention pruning, and CSV exports.
"""

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from app.storage.database import checkpoint_wal, get_connection, get_db_file_sizes
from app.storage.downsampling import (
    downsample_bucket_aggregation,
    downsample_lttb,
    downsample_stride,
)
from app.storage.models import (
    DetectionRecord,
    InferenceFrameRecord,
    SystemEventRecord,
    TelemetrySample,
)
from app.storage.repository import TelemetryRepository


def test_database_wal_mode_and_tables(test_repo, test_config):
    """Verify SQLite initialises in WAL mode with expected tables and indexes."""
    conn = get_connection(test_config.storage.db_path)
    cur = conn.execute("PRAGMA journal_mode;")
    mode = cur.fetchone()[0]
    assert mode.lower() == "wal"

    cur_sync = conn.execute("PRAGMA synchronous;")
    sync_mode = cur_sync.fetchone()[0]
    # 1 corresponds to NORMAL synchronous mode in SQLite
    assert sync_mode == 1

    # Verify tables exist
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        ).fetchall()
    ]
    assert "telemetry_samples" in tables
    assert "inference_frames" in tables
    assert "detections" in tables
    assert "system_events" in tables

    # Verify indices exist
    indices = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index';"
        ).fetchall()
    ]
    assert "idx_telemetry_ts_metric" in indices
    assert "idx_telemetry_metric_ts" in indices
    assert "idx_inference_ts" in indices
    assert "idx_detections_ts" in indices
    conn.close()


def test_checkpoint_wal_helper(test_repo, test_config):
    """Verify WAL checkpoint helper runs cleanly without locking errors."""
    samples = [
        TelemetrySample(
            metric_name="cpu_temp",
            value=45.0,
            unit="celsius",
            source="hwmon",
            availability_status="AVAILABLE",
        )
    ]
    test_repo.enqueue_telemetry(samples)
    time.sleep(0.2)

    busy, log_pages, checkpointed = checkpoint_wal(test_config.storage.db_path, "PASSIVE")
    assert busy == 0
    assert log_pages >= 0


def test_batched_telemetry_persistence_and_query(test_repo):
    """Verify non-blocking batched persistence and historical querying."""
    samples = [
        TelemetrySample(
            metric_name="cpu_temp",
            value=45.2,
            unit="celsius",
            source="hwmon",
            availability_status="AVAILABLE",
        ),
        TelemetrySample(
            metric_name="cpu_temp",
            value=46.1,
            unit="celsius",
            source="hwmon",
            availability_status="AVAILABLE",
        ),
    ]
    ok = test_repo.enqueue_telemetry(samples)
    assert ok is True
    time.sleep(0.3)  # Allow batch writer thread to flush

    history = test_repo.query_telemetry_history(metric_name="cpu_temp")
    assert len(history) >= 2
    assert history[0]["metric_name"] == "cpu_temp"


def test_non_blocking_enqueue_under_full_queue(tmp_path):
    """Verify queue shed behaviour when bounded queue capacity is exceeded."""
    small_db = str(tmp_path / "small_queue.db")
    repo = TelemetryRepository(
        db_path=small_db,
        batch_size=100,
        flush_interval_seconds=10.0,
        max_queue_size=2,
    )
    # Do not start worker thread so queue fills up immediately
    sample = [
        TelemetrySample(
            metric_name="test_metric",
            value=1.0,
            unit="test",
            source="test",
            availability_status="AVAILABLE",
        )
    ]

    ok1 = repo.enqueue_telemetry(sample)
    ok2 = repo.enqueue_telemetry(sample)
    # Queue size is 2, third enqueue must fail gracefully without blocking
    ok3 = repo.enqueue_telemetry(sample)

    assert ok1 is True
    assert ok2 is True
    assert ok3 is False
    assert repo._dropped_samples_count >= 1
    repo.stop()


def test_inference_frame_and_detection_persistence(test_repo):
    """Verify inference frame and detection bounding box records persist accurately."""
    frame = InferenceFrameRecord(
        frame_seq=1,
        source_id="file:test",
        timestamp_utc="2026-10-08T20:00:00Z",
        acquisition_ms=2.0,
        preprocessing_ms=1.5,
        hailo_exec_ms=4.8,
        postprocessing_ms=0.7,
        total_latency_ms=9.0,
        detections_count=1,
    )
    det = [
        DetectionRecord(
            frame_seq=1,
            timestamp_utc="2026-10-08T20:00:00Z",
            class_id=0,
            class_name="person",
            confidence=0.92,
            box_xmin=0.1,
            box_ymin=0.2,
            box_xmax=0.4,
            box_ymax=0.6,
        )
    ]
    test_repo.enqueue_inference(frame, det)
    time.sleep(0.3)

    frames = test_repo.query_inference_history()
    assert len(frames) >= 1

    dets = test_repo.query_detections_history(class_name="person")
    assert len(dets) >= 1
    assert dets[0]["class_name"] == "person"


def test_downsampling_algorithms_unit():
    """Verify pure-Python LTTB, bucket aggregation, and stride downsampling algorithms."""
    base_time = datetime(2026, 10, 13, 10, 0, 0, tzinfo=timezone.utc)
    # Generate 50 points with a prominent peak in the middle
    data = []
    for i in range(50):
        t_str = (base_time + timedelta(seconds=i)).isoformat()
        val = 10.0 + (50.0 if i == 25 else (i * 0.2))
        data.append({"timestamp_utc": t_str, "value": val, "metric_name": "temp"})

    # 1. Stride downsampling
    strided = downsample_stride(data, stride=5)
    assert len(strided) == 10

    # 2. LTTB downsampling
    lttb_sampled = downsample_lttb(data, target_points=10)
    assert len(lttb_sampled) == 10
    # First and last points preserved
    assert lttb_sampled[0]["timestamp_utc"] == data[0]["timestamp_utc"]
    assert lttb_sampled[-1]["timestamp_utc"] == data[-1]["timestamp_utc"]
    # Check that prominent peak (index 25, value 60.0) is retained
    values = [p["value"] for p in lttb_sampled]
    assert 60.0 in values

    # 3. Bucket aggregation downsampling
    bucket_sampled = downsample_bucket_aggregation(data, target_points=5)
    assert len(bucket_sampled) <= 5
    for b in bucket_sampled:
        assert "min_value" in b
        assert "max_value" in b
        assert "sample_count" in b
        assert b["min_value"] <= b["value"] <= b["max_value"]


def test_repository_query_downsampling_integration(test_repo):
    """Verify integration of downsampling with repository query methods."""
    base_time = datetime.now(timezone.utc)
    samples = []
    for i in range(40):
        t_str = (base_time + timedelta(seconds=i)).isoformat()
        samples.append(
            TelemetrySample(
                timestamp_utc=t_str,
                metric_name="downsample_test",
                value=20.0 + float(i),
                unit="celsius",
                source="test",
                availability_status="AVAILABLE",
            )
        )
    test_repo.enqueue_telemetry(samples)
    time.sleep(0.3)

    # Query with LTTB
    lttb_results = test_repo.query_telemetry_history(
        metric_name="downsample_test",
        target_points=8,
        method="lttb",
    )
    assert len(lttb_results) == 8

    # Query with Bucket aggregation
    bucket_results = test_repo.query_telemetry_history(
        metric_name="downsample_test",
        target_points=5,
        method="bucket",
    )
    assert len(bucket_results) <= 5
    assert "min_value" in bucket_results[0]

    # Query with dedicated downsample method
    dedicated = test_repo.query_downsampled_metrics(
        metric_name="downsample_test",
        target_points=10,
        method="lttb",
    )
    assert len(dedicated) == 10


def test_retention_pruning_manual(test_repo):
    """Verify manual retention pruning purges expired records and retains recent records."""
    old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    recent_time = datetime.now(timezone.utc).isoformat()

    old_sample = [
        TelemetrySample(
            timestamp_utc=old_time,
            metric_name="retention_metric",
            value=10.0,
            unit="unit",
            source="test",
            availability_status="AVAILABLE",
        )
    ]
    recent_sample = [
        TelemetrySample(
            timestamp_utc=recent_time,
            metric_name="retention_metric",
            value=20.0,
            unit="unit",
            source="test",
            availability_status="AVAILABLE",
        )
    ]

    test_repo.enqueue_telemetry(old_sample)
    test_repo.enqueue_telemetry(recent_sample)
    time.sleep(0.3)

    # Verify both exist initially
    initial = test_repo.query_telemetry_history(metric_name="retention_metric")
    assert len(initial) == 2

    # Prune records older than 24 hours
    summary = test_repo.prune_retention(retention_hours=24.0)
    assert summary["purged_telemetry"] >= 1

    remaining = test_repo.query_telemetry_history(metric_name="retention_metric")
    assert len(remaining) == 1
    assert remaining[0]["value"] == 20.0


def test_automated_retention_prune_worker_loop(tmp_path):
    """Verify background worker loop automatically executes retention pruning."""
    db_file = str(tmp_path / "auto_prune.db")
    repo = TelemetryRepository(
        db_path=db_file,
        batch_size=2,
        flush_interval_seconds=0.05,
        retention_hours=1.0,
        prune_interval_seconds=0.1,  # Short interval for automated test
    )
    repo.start()

    # Enqueue a sample older than 2 hours
    old_time = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    old_sample = [
        TelemetrySample(
            timestamp_utc=old_time,
            metric_name="auto_prune_metric",
            value=99.0,
            unit="unit",
            source="test",
            availability_status="AVAILABLE",
        )
    ]
    repo.enqueue_telemetry(old_sample)

    # Allow worker thread to flush and trigger automated pruning cycle
    time.sleep(0.35)

    remaining = repo.query_telemetry_history(metric_name="auto_prune_metric")
    assert len(remaining) == 0
    assert repo._total_purged_records >= 1
    repo.stop()


def test_csv_export_and_streaming(test_repo):
    """Verify complete CSV export and chunked generator streaming."""
    samples = [
        TelemetrySample(
            metric_name="voltage_5v",
            value=5.02,
            unit="volts",
            source="rp1",
            availability_status="AVAILABLE",
        )
    ]
    test_repo.enqueue_telemetry(samples)
    time.sleep(0.3)

    # Telemetry CSV
    csv_str = test_repo.export_telemetry_csv()
    assert "timestamp_utc,metric_name,value,unit" in csv_str
    assert "voltage_5v" in csv_str

    # Streaming Telemetry CSV chunks
    chunks = list(test_repo.stream_telemetry_csv(metric_name="voltage_5v"))
    assert len(chunks) >= 1
    assert any("voltage_5v" in c for c in chunks)

    # Waveforms CSV
    wf_csv = test_repo.export_waveforms_csv()
    assert "timestamp_utc" in wf_csv

    # Streaming Waveforms CSV
    wf_chunks = list(test_repo.stream_waveforms_csv())
    assert len(wf_chunks) >= 1


def test_storage_diagnostics_stats(test_repo):
    """Verify storage diagnostics and statistics reporting."""
    stats = test_repo.get_storage_stats()
    assert "db_path" in stats
    assert stats["journal_mode"] == "wal"
    assert "file_sizes" in stats
    assert "total_records" in stats
    assert "queue" in stats
    assert "retention" in stats


def test_reset_history(test_repo):
    """Verify resetting history clears records and SQLite WAL pages."""
    samples = [
        TelemetrySample(
            metric_name="reset_temp",
            value=48.0,
            unit="celsius",
            source="hwmon",
            availability_status="AVAILABLE",
        )
    ]
    test_repo.enqueue_telemetry(samples)
    time.sleep(0.3)
    assert len(test_repo.query_telemetry_history(metric_name="reset_temp")) >= 1

    deleted = test_repo.reset_history()
    assert deleted["telemetry"] >= 1
    assert len(test_repo.query_telemetry_history(metric_name="reset_temp")) == 0
