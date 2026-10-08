"""
Unit tests for SQLite database schema, WAL mode, batched writes, and queries.
"""

import time
import pytest

from app.storage.database import get_connection
from app.storage.models import (
    DetectionRecord,
    InferenceFrameRecord,
    SystemEventRecord,
    TelemetrySample,
)
from app.storage.repository import TelemetryRepository


def test_database_wal_mode_and_tables(test_repo, test_config):
    conn = get_connection(test_config.storage.db_path)
    cur = conn.execute("PRAGMA journal_mode;")
    mode = cur.fetchone()[0]
    assert mode.lower() == "wal"

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
    conn.close()


def test_batched_telemetry_persistence_and_query(test_repo):
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
    test_repo.enqueue_telemetry(samples)
    time.sleep(0.3)  # Allow batch writer thread to flush

    history = test_repo.query_telemetry_history(metric_name="cpu_temp")
    assert len(history) >= 2
    assert history[0]["metric_name"] == "cpu_temp"


def test_inference_frame_and_detection_persistence(test_repo):
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


def test_csv_export(test_repo):
    csv_str = test_repo.export_telemetry_csv()
    assert "timestamp_utc,metric_name,value,unit" in csv_str
