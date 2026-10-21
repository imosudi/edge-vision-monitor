"""
Unit tests for RollingLatencyTracker, TrajectoryPoint, TrajectorySession,
TrajectoryEngine, and structured CSV/JSON trajectory exports.
"""

import csv
import json
import os
import time
from datetime import datetime, timezone
import pytest

from app.services.inference_service import RollingLatencyTracker
from app.storage.models import InferenceFrameRecord, TelemetrySample
from app.telemetry.trajectory import (
    CSV_FIELDNAMES,
    TrajectoryEngine,
    TrajectoryPoint,
    TrajectorySession,
    get_trajectory_engine,
)


def test_rolling_latency_tracker_empty():
    tracker = RollingLatencyTracker(window_size=50)
    stats = tracker.get_stats()
    assert stats["count"] == 0.0
    assert stats["mean"] == 0.0
    assert stats["median"] == 0.0
    assert stats["p50"] == 0.0
    assert stats["p95"] == 0.0
    assert stats["p99"] == 0.0
    assert stats["min"] == 0.0
    assert stats["max"] == 0.0


def test_rolling_latency_tracker_percentiles():
    tracker = RollingLatencyTracker(window_size=100)
    # Add values 1.0 to 100.0
    for i in range(1, 101):
        tracker.add(float(i))

    stats = tracker.get_stats()
    assert stats["count"] == 100.0
    assert stats["min"] == 1.0
    assert stats["max"] == 100.0
    assert stats["p50"] == 51.0
    assert stats["p95"] == 96.0
    assert stats["p99"] == 100.0
    assert 50.0 <= stats["mean"] <= 51.0


def test_trajectory_point_to_csv_and_dict():
    pt = TrajectoryPoint(
        timestamp_utc="2026-10-21T11:00:00Z",
        monotonic_ts=100.0,
        relative_seconds=5.1234,
        workload_name="Workload A",
        ts0_c=48.2,
        ts1_c=49.1,
        tj_c=49.1,
        clock_mhz=400.0,
        throttling_level=0,
        throttling_active=True,
        fps=25.4,
        cpu_load_percent=34.2,
        cpu_temp_c=52.0,
        fan_rpm=2400.0,
        npu_util_percent=42.5,
        lat_pre_p50_ms=1.2,
        lat_pre_p95_ms=2.1,
        lat_pre_p99_ms=3.0,
        lat_npu_p50_ms=14.5,
        lat_npu_p95_ms=15.2,
        lat_npu_p99_ms=16.1,
        lat_post_p50_ms=22.0,
        lat_post_p95_ms=24.5,
        lat_post_p99_ms=26.0,
        lat_total_p50_ms=37.7,
        lat_total_p95_ms=41.8,
        lat_total_p99_ms=45.1,
    )

    d = pt.to_dict()
    assert d["workload_name"] == "Workload A"
    assert d["relative_seconds"] == 5.123
    assert d["tj_c"] == 49.1
    assert d["throttling_active"] is True

    row = pt.to_csv_row()
    for col in CSV_FIELDNAMES:
        assert col in row
    assert row["workload"] == "Workload A"
    assert row["hailo_tj_c"] == "49.1"
    assert row["hailo_clock_mhz"] == "400.0"
    assert row["hailo_throttling_active"] == "1"
    assert row["inference_fps"] == "25.4"
    assert row["fan_rpm"] == "2400"


def test_trajectory_session_export_csv_and_json(temp_dir):
    session = TrajectorySession(session_id="test_sess_01", workload_name="Workload B")
    pt1 = TrajectoryPoint(
        timestamp_utc="2026-10-21T11:00:00Z",
        monotonic_ts=100.0,
        relative_seconds=0.0,
        workload_name="Workload B",
        ts0_c=45.0,
        ts1_c=44.0,
        tj_c=45.0,
        clock_mhz=400.0,
        throttling_level=None,
        throttling_active=False,
        fps=20.0,
    )
    pt2 = TrajectoryPoint(
        timestamp_utc="2026-10-21T11:00:05Z",
        monotonic_ts=105.0,
        relative_seconds=5.0,
        workload_name="Workload B",
        ts0_c=55.0,
        ts1_c=56.0,
        tj_c=56.0,
        clock_mhz=350.0,
        throttling_level=0,
        throttling_active=True,
        fps=18.5,
    )
    session.add_point(pt1)
    session.add_point(pt2)
    session.close()

    summary = session.summary()
    assert summary["session_id"] == "test_sess_01"
    assert summary["total_points"] == 2
    assert summary["thermals_c"]["tj_initial"] == 45.0
    assert summary["thermals_c"]["tj_peak"] == 56.0
    assert summary["throttling"]["throttling_occurred"] is True

    csv_data = session.export_csv()
    lines = csv_data.strip().split("\r\n")
    assert len(lines) == 3  # Header + 2 rows
    assert "timestamp_utc,relative_seconds,workload" in lines[0]

    json_data = session.export_json()
    assert json_data["session_id"] == "test_sess_01"
    assert len(json_data["points"]) == 2

    # Verify saving to disk
    csv_file = os.path.join(temp_dir, "trajectory.csv")
    session.save_csv(csv_file)
    assert os.path.exists(csv_file)
    assert os.path.getsize(csv_file) > 0

    json_file = os.path.join(temp_dir, "trajectory.json")
    session.save_json(json_file)
    assert os.path.exists(json_file)
    assert os.path.getsize(json_file) > 0


def test_trajectory_engine_capture_point():
    engine = TrajectoryEngine(ring_buffer_capacity=100)
    engine.start_session("Workload C")

    metrics_snap = {
        "hailo_temp_ts0_c": {"value": 50.1},
        "hailo_temp_ts1_c": {"value": 51.5},
        "hailo_junction_temperature_c": {"value": 51.5},
        "hailo_clock_frequency_mhz": {"value": 400.0},
        "hailo_throttling_level": {"value": -1},
        "hailo_throttling_active": {"value": 0.0},
        "hailo_utilization_percent": {"value": 38.0},
        "cpu_utilisation_percent": {"value": 25.5},
        "cpu_temperature_c": {"value": 47.0},
        "hwmon_pwmfan_fan1_rpm": {"value": 2100.0},
    }

    inf_stats = {
        "current_fps": 22.8,
        "latencies": {
            "preprocessing_ms": {"p50": 1.4, "p95": 2.0, "p99": 2.5},
            "execution_ms": {"p50": 14.8, "p95": 15.5, "p99": 16.0},
            "postprocessing_ms": {"p50": 24.1, "p95": 26.0, "p99": 28.0},
            "total_ms": {"p50": 40.3, "p95": 43.5, "p99": 46.5},
        },
    }

    pt = engine.capture_point(metrics_snap, inf_stats)
    assert pt.workload_name == "Workload C"
    assert pt.ts0_c == 50.1
    assert pt.ts1_c == 51.5
    assert pt.tj_c == 51.5
    assert pt.clock_mhz == 400.0
    assert pt.throttling_active is False
    assert pt.fps == 22.8
    assert pt.cpu_load_percent == 25.5
    assert pt.fan_rpm == 2100.0
    assert pt.lat_npu_p50_ms == 14.8
    assert pt.lat_total_p95_ms == 43.5

    active_sess = engine.get_active_session()
    assert active_sess is not None
    assert len(active_sess.points) == 1

    engine.stop_session()
    assert engine.is_recording() is False


def test_trajectory_engine_reconstruct_from_repository(test_repo):
    test_repo.start()
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        samples = [
            TelemetrySample(
                metric_name="hailo_temp_ts0_c",
                value=46.2,
                unit="celsius",
                source="hailort",
                availability_status="AVAILABLE",
                timestamp_utc=now_iso,
            ),
            TelemetrySample(
                metric_name="hailo_temp_ts1_c",
                value=47.1,
                unit="celsius",
                source="hailort",
                availability_status="AVAILABLE",
                timestamp_utc=now_iso,
            ),
            TelemetrySample(
                metric_name="hailo_clock_frequency_mhz",
                value=400.0,
                unit="megahertz",
                source="hailort",
                availability_status="AVAILABLE",
                timestamp_utc=now_iso,
            ),
            TelemetrySample(
                metric_name="hwmon_pwmfan_fan1_rpm",
                value=2500.0,
                unit="rpm",
                source="hwmon",
                availability_status="AVAILABLE",
                timestamp_utc=now_iso,
            ),
        ]
        test_repo.enqueue_telemetry(samples)

        frame = InferenceFrameRecord(
            frame_seq=1,
            source_id="cam0",
            timestamp_utc=now_iso,
            acquisition_ms=5.0,
            preprocessing_ms=1.3,
            hailo_exec_ms=14.7,
            postprocessing_ms=23.5,
            total_latency_ms=39.5,
            detections_count=3,
        )
        test_repo.enqueue_inference(frame, [])
        time.sleep(0.3)

        # Test TelemetryRepository export methods
        csv_out = test_repo.export_trajectory_csv()
        assert "timestamp_utc,relative_seconds,workload" in csv_out
        assert "47.1" in csv_out  # TS1 / Tj

        json_out = test_repo.export_trajectory_json()
        assert "points" in json_out
        assert len(json_out["points"]) >= 1

        chunks = list(test_repo.stream_trajectory_csv())
        combined = "".join(chunks)
        assert "timestamp_utc,relative_seconds,workload" in combined

    finally:
        test_repo.stop()
