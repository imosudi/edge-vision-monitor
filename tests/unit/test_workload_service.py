"""
Unit tests for Thermal Stress Generator and Workload Service (Phase 3).
Validates Workload Suite (A, B, C, D) execution, thermal safety abort,
throttling governor response validation, and CSV/JSON trajectory exports.
"""

import csv
import json
import os
import time
import pytest

from app.core.config import VideoSourceConfig
from app.services.workload_service import (
    HARD_SAFETY_LIMIT_C,
    THROTTLING_RECOVERY_TEMP_C,
    ThermalStressGenerator,
    WorkloadService,
)
from app.sources.manager import VideoSourceManager
from app.sources.multi_stream_source import MultiStreamSource
from app.telemetry.trajectory import TrajectoryEngine


class MockInferenceService:
    def __init__(self):
        self.benchmark_mode = False
        self.fps = 26.5
        self.running = False

    def is_running(self) -> bool:
        return self.running

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def set_benchmark_mode(self, enabled: bool):
        self.benchmark_mode = enabled

    def get_stats(self):
        return {
            "current_fps": self.fps,
            "latencies": {
                "preprocessing_ms": {"p50": 1.2, "p95": 1.8, "p99": 2.1},
                "execution_ms": {"p50": 15.1, "p95": 18.2, "p99": 21.0},
                "postprocessing_ms": {"p50": 22.4, "p95": 28.5, "p99": 34.0},
                "total_ms": {"p50": 38.7, "p95": 48.5, "p99": 57.1},
            },
        }


class MockTelemetryService:
    def __init__(self, tj_c: float = 52.0):
        self.tj_c = tj_c
        self.clock_mhz = 400.0
        self.throttling_level = 0
        self.throttling_active = 0.0

    def get_current_metrics(self):
        return {
            "hailo_junction_temperature_c": {"value": self.tj_c},
            "hailo_temp_ts0_c": {"value": self.tj_c - 0.5},
            "hailo_temp_ts1_c": {"value": self.tj_c + 0.5},
            "hailo_clock_frequency_mhz": {"value": self.clock_mhz},
            "hailo_throttling_level": {"value": self.throttling_level},
            "hailo_throttling_active": {"value": self.throttling_active},
            "cpu_temperature_c": {"value": 46.0},
            "cpu_utilisation_percent": {"value": 24.5},
            "hwmon_pwmfan_fan1_rpm": {"value": 3200.0},
        }


class MockEventService:
    def __init__(self):
        self.events = []

    def emit(self, event_type: str, message: str, severity: str = "INFO", component: str = "WORKLOAD"):
        self.events.append({
            "type": event_type,
            "message": message,
            "severity": severity,
            "component": component,
        })


@pytest.fixture
def workload_env(temp_dir):
    """Fixture providing isolated VideoSourceManager and mock dependencies with teardown."""
    src_cfg = VideoSourceConfig(default_source_type="file", media_dir=temp_dir)
    src_mgr = VideoSourceManager(src_cfg)
    inf_svc = MockInferenceService()
    tel_svc = MockTelemetryService(tj_c=50.0)
    evt_svc = MockEventService()
    engine = TrajectoryEngine()

    yield {
        "src_mgr": src_mgr,
        "inf_svc": inf_svc,
        "tel_svc": tel_svc,
        "evt_svc": evt_svc,
        "engine": engine,
    }

    src_mgr.stop()


def test_workload_type_normalisation():
    assert WorkloadService.normalise_workload_type("A") == "A"
    assert WorkloadService.normalise_workload_type("b") == "B"
    assert WorkloadService.normalise_workload_type("workload_c") == "C"
    assert WorkloadService.normalise_workload_type("WORKLOAD_D") == "D"

    with pytest.raises(ValueError):
        WorkloadService.normalise_workload_type("E")

    with pytest.raises(ValueError):
        WorkloadService.normalise_workload_type("invalid_workload")


def test_workload_a_lifecycle(workload_env):
    src_mgr = workload_env["src_mgr"]
    inf_svc = workload_env["inf_svc"]
    tel_svc = workload_env["tel_svc"]
    evt_svc = workload_env["evt_svc"]
    engine = workload_env["engine"]

    svc = WorkloadService(
        source_manager=src_mgr,
        inference_service=inf_svc,
        telemetry_service=tel_svc,
        event_service=evt_svc,
        trajectory_engine=engine,
    )

    # 1. Start Workload A
    status = svc.start_workload(
        workload_type="A",
        duration_seconds=5.0,
        buffer_size=20,
    )
    assert status["active"] is True
    assert status["state"] == "running"
    assert status["workload_type"] == "A"
    assert inf_svc.benchmark_mode is True
    assert src_mgr.get_status()["active_type"] == "ring_buffer"

    # Verify double-start rejection
    with pytest.raises(RuntimeError):
        svc.start_workload(workload_type="A")

    # Let supervisor sample
    time.sleep(0.25)
    live_status = svc.get_status()
    assert live_status["samples_count"] > 0
    assert live_status["current_tj_c"] is not None

    # 2. Stop Workload A cleanly
    stop_status = svc.stop_workload(reason="Test completion")
    assert stop_status["active"] is False
    assert stop_status["state"] in ("completed", "aborted")
    assert inf_svc.benchmark_mode is False
    assert src_mgr.get_status()["active_type"] == "file"

    # Check session recorded in history
    history = svc.get_session_history()
    assert len(history) == 1
    assert history[0]["workload_name"] == "workload_a"


def test_workload_b_multi_stream(workload_env):
    src_mgr = workload_env["src_mgr"]
    inf_svc = workload_env["inf_svc"]
    tel_svc = workload_env["tel_svc"]
    evt_svc = workload_env["evt_svc"]
    engine = workload_env["engine"]

    svc = WorkloadService(
        source_manager=src_mgr,
        inference_service=inf_svc,
        telemetry_service=tel_svc,
        event_service=evt_svc,
        trajectory_engine=engine,
    )

    status = svc.start_workload(
        workload_type="B",
        duration_seconds=5.0,
        stream_count=3,
        buffer_size=30,
    )
    assert status["workload_type"] == "B"
    assert src_mgr.get_status()["active_type"] == "multi_stream"

    time.sleep(0.2)
    svc.stop_workload()
    assert svc.get_status()["active"] is False


def test_workload_c_safety_abort(workload_env):
    src_mgr = workload_env["src_mgr"]
    inf_svc = workload_env["inf_svc"]
    tel_svc = workload_env["tel_svc"]
    # Mock temperature exceeding safety threshold (75.0°C in this test)
    tel_svc.tj_c = 78.5
    evt_svc = workload_env["evt_svc"]
    engine = workload_env["engine"]

    svc = WorkloadService(
        source_manager=src_mgr,
        inference_service=inf_svc,
        telemetry_service=tel_svc,
        event_service=evt_svc,
        trajectory_engine=engine,
    )

    # Configure safety threshold at 70.0°C
    status = svc.start_workload(
        workload_type="C",
        duration_seconds=10.0,
        safety_temp_limit_c=70.0,
        target_temp_c=68.0,
    )

    # Supervisor loop should instantly trigger safety abort within ~0.2s
    time.sleep(0.35)

    final_st = svc.get_status()
    assert final_st["active"] is False
    assert final_st["state"] == "aborted"
    assert "Safety abort triggered" in (final_st["abort_reason"] or "")
    assert inf_svc.benchmark_mode is False

    # Verify critical event was emitted
    critical_events = [e for e in evt_svc.events if e["severity"] == "CRITICAL"]
    assert len(critical_events) >= 1
    assert "THERMAL_SAFETY_ABORT" in critical_events[0]["type"]


def test_workload_d_throttling_simulation_full_sequence(workload_env):
    """
    Workload D simulation test: verifies full throttle-and-recovery sequence,
    alert events, governor step-down (400 -> 200 MHz), and hysteresis recovery
    below 99.0°C without heating the physical device, approaching just below
    the critical limit to protect the hardware.
    """
    src_mgr = workload_env["src_mgr"]
    inf_svc = workload_env["inf_svc"]
    tel_svc = workload_env["tel_svc"]
    evt_svc = workload_env["evt_svc"]
    engine = workload_env["engine"]

    svc = WorkloadService(
        source_manager=src_mgr,
        inference_service=inf_svc,
        telemetry_service=tel_svc,
        event_service=evt_svc,
        trajectory_engine=engine,
    )

    # Start Workload D with simulation enabled
    status = svc.start_workload(
        workload_type="D",
        duration_seconds=5.0,
        simulate=True,
    )
    assert status["workload_type"] == "D"
    assert status["active"] is True
    assert inf_svc.benchmark_mode is True

    # Poll through the two-phase simulation cycle (ramp up to ~101°C, then cooldown to <99°C)
    throttling_hit = False
    recovery_hit = False
    deadline = time.monotonic() + 3.0

    while time.monotonic() < deadline:
        st = svc.get_status()
        if st.get("throttling_observed"):
            throttling_hit = True
        if st.get("hysteresis_recovered"):
            recovery_hit = True
            break
        time.sleep(0.05)

    assert throttling_hit is True, "Governor throttling was not engaged during simulation ramp"
    assert recovery_hit is True, "Hysteresis recovery below 99.0°C was not achieved during cooldown"

    live_st = svc.get_status()
    # 1. Assert governor clock step-down occurred
    assert live_st["min_clock_mhz"] == 200.0
    # 2. Assert clock returned to nominal after recovery
    assert live_st["clock_frequency_mhz"] == 400.0
    assert live_st["throttling_active"] is False
    assert live_st["hysteresis_recovered"] is True

    # 3. Assert peak junction temperature approached just below critical limit to protect hardware
    peak_tj = live_st["peak_tj_c"]
    assert peak_tj is not None
    assert 100.0 <= peak_tj < HARD_SAFETY_LIMIT_C, f"Peak {peak_tj}°C must stay below {HARD_SAFETY_LIMIT_C}°C"
    assert live_st["state"] == "running", "Workload should not abort when remaining below critical safety limit"

    # 4. Assert alert and recovery events were emitted
    engaged_events = [e for e in evt_svc.events if e["type"] == "THROTTLING_ENGAGED"]
    assert len(engaged_events) >= 1
    assert engaged_events[0]["severity"] == "WARNING"
    assert engaged_events[0]["component"] == "SAFETY"

    recovered_events = [e for e in evt_svc.events if e["type"] == "THROTTLING_RECOVERED"]
    assert len(recovered_events) >= 1
    assert recovered_events[0]["severity"] == "INFO"
    assert recovered_events[0]["component"] == "SAFETY"

    # 5. Stop cleanly and verify trajectory summary audit trail
    stop_st = svc.stop_workload(reason="Full sequence validated")
    assert stop_st["active"] is False
    eval_info = stop_st["session_summary"]["workload_evaluation"]
    assert eval_info["throttling_observed"] is True
    assert eval_info["hysteresis_recovered"] is True
    assert eval_info["safety_abort_triggered"] is False
    assert eval_info["peak_tj_c"] < HARD_SAFETY_LIMIT_C


def test_workload_d_simulation_safety_abort(workload_env):
    """
    Workload D simulation test: verifies software's safety abort path when
    junction temperature breaches the critical limit, protecting hardware.
    """
    src_mgr = workload_env["src_mgr"]
    inf_svc = workload_env["inf_svc"]
    tel_svc = workload_env["tel_svc"]
    evt_svc = workload_env["evt_svc"]
    engine = workload_env["engine"]

    svc = WorkloadService(
        source_manager=src_mgr,
        inference_service=inf_svc,
        telemetry_service=tel_svc,
        event_service=evt_svc,
        trajectory_engine=engine,
    )

    # Set safety limit below the simulation ramp target (e.g. 98.5°C) to test abort path
    status = svc.start_workload(
        workload_type="D",
        duration_seconds=5.0,
        safety_temp_limit_c=98.5,
        simulate=True,
    )
    assert status["active"] is True

    # Wait for temperature to exceed 98.5°C and trigger safety abort
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline and svc.get_status()["active"]:
        time.sleep(0.05)

    final_st = svc.get_status()
    assert final_st["active"] is False
    assert final_st["state"] == "aborted"
    assert "Safety abort triggered" in (final_st["abort_reason"] or "")
    assert inf_svc.benchmark_mode is False

    # Verify critical event was emitted to alert system
    abort_events = [e for e in evt_svc.events if e["type"] == "THERMAL_SAFETY_ABORT"]
    assert len(abort_events) >= 1
    assert abort_events[0]["severity"] == "CRITICAL"


def test_workload_d_hardware_approach_below_critical_limit_and_recovery(workload_env):
    """
    Workload D hardware telemetry test: simulates real hardware readings
    approaching just below the critical limit (101.4°C < 102.0°C) to protect
    the physical hardware, verifying throttling alert and hysteresis recovery.
    """
    src_mgr = workload_env["src_mgr"]
    inf_svc = workload_env["inf_svc"]
    tel_svc = workload_env["tel_svc"]
    tel_svc.tj_c = 55.0
    tel_svc.clock_mhz = 400.0
    evt_svc = workload_env["evt_svc"]
    engine = workload_env["engine"]

    svc = WorkloadService(
        source_manager=src_mgr,
        inference_service=inf_svc,
        telemetry_service=tel_svc,
        event_service=evt_svc,
        trajectory_engine=engine,
    )

    status = svc.start_workload(
        workload_type="D",
        duration_seconds=10.0,
        safety_temp_limit_c=HARD_SAFETY_LIMIT_C,
        simulate=False,
    )
    assert status["active"] is True

    # 1. Hardware approaches just below the critical limit (101.4°C < 102.0°C)
    tel_svc.tj_c = 101.4
    tel_svc.clock_mhz = 200.0
    tel_svc.throttling_level = 1
    tel_svc.throttling_active = 1.0

    time.sleep(0.3)
    live_st = svc.get_status()
    assert live_st["active"] is True, "Must not abort when temperature is strictly below critical limit"
    assert live_st["throttling_observed"] is True
    assert live_st["throttling_active"] is True
    assert live_st["clock_frequency_mhz"] == 200.0
    assert live_st["peak_tj_c"] == 101.4

    # Verify warning alert was emitted
    alert_events = [e for e in evt_svc.events if e["type"] == "THROTTLING_ENGAGED"]
    assert len(alert_events) >= 1
    assert alert_events[0]["severity"] == "WARNING"

    # 2. Hardware cools down below the hysteresis recovery threshold (< 99.0°C)
    tel_svc.tj_c = 98.2
    tel_svc.clock_mhz = 400.0
    tel_svc.throttling_level = 0
    tel_svc.throttling_active = 0.0

    time.sleep(0.3)
    live_st2 = svc.get_status()
    assert live_st2["hysteresis_recovered"] is True
    assert live_st2["throttling_active"] is False
    assert live_st2["clock_frequency_mhz"] == 400.0

    # Verify recovery event was emitted
    recovery_events = [e for e in evt_svc.events if e["type"] == "THROTTLING_RECOVERED"]
    assert len(recovery_events) >= 1
    assert recovery_events[0]["severity"] == "INFO"

    # Stop and verify evaluation summary
    stop_st = svc.stop_workload(reason="Hardware telemetry verified")
    assert stop_st["active"] is False
    eval_info = stop_st["session_summary"]["workload_evaluation"]
    assert eval_info["throttling_observed"] is True
    assert eval_info["hysteresis_recovered"] is True
    assert eval_info["safety_abort_triggered"] is False
    assert eval_info["peak_tj_c"] == 101.4


def test_workload_d_hardware_safety_abort_when_critical_limit_exceeded(workload_env):
    """
    Workload D hardware telemetry test: verifies that if real hardware temperature
    exceeds HARD_SAFETY_LIMIT_C (102.0°C), the safety abort triggers instantly
    to protect physical silicon.
    """
    src_mgr = workload_env["src_mgr"]
    inf_svc = workload_env["inf_svc"]
    tel_svc = workload_env["tel_svc"]
    tel_svc.tj_c = 55.0
    evt_svc = workload_env["evt_svc"]
    engine = workload_env["engine"]

    svc = WorkloadService(
        source_manager=src_mgr,
        inference_service=inf_svc,
        telemetry_service=tel_svc,
        event_service=evt_svc,
        trajectory_engine=engine,
    )

    status = svc.start_workload(
        workload_type="D",
        duration_seconds=10.0,
        safety_temp_limit_c=HARD_SAFETY_LIMIT_C,
        simulate=False,
    )
    assert status["active"] is True

    # Hardware exceeds critical safety threshold
    tel_svc.tj_c = 102.5
    time.sleep(0.35)

    final_st = svc.get_status()
    assert final_st["active"] is False
    assert final_st["state"] == "aborted"
    assert "Safety abort triggered" in (final_st["abort_reason"] or "")
    assert inf_svc.benchmark_mode is False

    abort_events = [e for e in evt_svc.events if e["type"] == "THERMAL_SAFETY_ABORT"]
    assert len(abort_events) >= 1
    assert abort_events[0]["severity"] == "CRITICAL"


def test_trajectory_exports_csv_and_json(workload_env):
    src_mgr = workload_env["src_mgr"]
    inf_svc = workload_env["inf_svc"]
    tel_svc = workload_env["tel_svc"]
    tel_svc.tj_c = 55.0
    engine = workload_env["engine"]

    svc = WorkloadService(
        source_manager=src_mgr,
        inference_service=inf_svc,
        telemetry_service=tel_svc,
        trajectory_engine=engine,
    )

    svc.start_workload(workload_type="A", duration_seconds=5.0)
    # Manually capture a trajectory point into engine to ensure points exist
    engine.capture_point(
        metrics_snapshot=tel_svc.get_current_metrics(),
        inference_stats=inf_svc.get_stats(),
        workload_name="workload_a",
    )
    time.sleep(0.15)
    st = svc.stop_workload()
    sess_id = st["session_id"]

    # 1. Test CSV export
    csv_str = svc.export_trajectory_csv(sess_id)
    assert len(csv_str) > 0
    reader = csv.reader(csv_str.splitlines())
    header = next(reader)
    assert "timestamp_utc" in header
    assert "hailo_tj_c" in header
    assert "inference_fps" in header

    # 2. Test JSON export
    json_data = svc.export_trajectory_json(sess_id)
    assert json_data["session_id"] == sess_id
    assert json_data["workload_name"] == "workload_a"
    assert "summary" in json_data
    assert "points" in json_data


def test_workload_ingress_file_selection(workload_env, temp_dir):
    """Verify that WorkloadService passes user selected media file into ingress feeder."""
    src_mgr = workload_env["src_mgr"]
    inf_svc = workload_env["inf_svc"]
    tel_svc = workload_env["tel_svc"]
    engine = workload_env["engine"]

    dummy_file = os.path.join(temp_dir, "test_video.mp4")
    with open(dummy_file, "wb") as f:
        f.write(b"0" * 1024)

    svc = WorkloadService(
        source_manager=src_mgr,
        inference_service=inf_svc,
        telemetry_service=tel_svc,
        trajectory_engine=engine,
    )

    st = svc.start_workload(
        workload_type="A",
        duration_seconds=5.0,
        media_file="test_video.mp4",
        simulate=True,
    )
    assert st["active"] is True
    assert svc._media_file == "test_video.mp4"

    svc.stop_workload()
    assert svc.get_status()["active"] is False


def test_multi_stream_candidate_file_resolution(temp_dir):
    """Verify MultiStreamSource resolves relative and basename file paths inside media_dir."""
    dummy_name = "sample_footage.mp4"
    dummy_path = os.path.join(temp_dir, dummy_name)
    with open(dummy_path, "wb") as f:
        f.write(b"0" * 1024)

    src = MultiStreamSource(
        stream_count=2,
        file_paths=[dummy_name],
        media_dir=temp_dir,
    )
    candidates = src._discover_candidate_files()
    assert len(candidates) == 1
    assert candidates[0] == dummy_path


def test_workload_ensures_inference_service_running(workload_env):
    """Verify start_workload starts inference_service if not already running."""
    src_mgr = workload_env["src_mgr"]
    inf_svc = workload_env["inf_svc"]
    tel_svc = workload_env["tel_svc"]
    engine = workload_env["engine"]

    inf_svc.running = False

    svc = WorkloadService(
        source_manager=src_mgr,
        inference_service=inf_svc,
        telemetry_service=tel_svc,
        trajectory_engine=engine,
    )

    svc.start_workload(workload_type="A", duration_seconds=5.0, simulate=True)
    assert inf_svc.is_running() is True
    assert inf_svc.benchmark_mode is True

    svc.stop_workload()
    assert inf_svc.benchmark_mode is False


def test_workload_microservices_ipc_dispatch():
    """Verify WorkloadService dispatches IPC commands when source_manager and inference_service are None."""
    from unittest.mock import patch
    from app.telemetry.trajectory import TrajectoryEngine

    engine = TrajectoryEngine()
    svc = WorkloadService(
        source_manager=None,
        inference_service=None,
        telemetry_service=None,
        trajectory_engine=engine,
    )

    with patch("app.core.ipc.send_ipc_inference_command") as mock_inf_cmd, \
         patch("app.core.ipc.send_ipc_source_command") as mock_src_cmd, \
         patch("app.core.ipc.get_ipc_source_status", return_value={"active_type": "file", "source_id": "file:test.mp4"}):

        # Start Workload B with 8 streams
        svc.start_workload(workload_type="B", duration_seconds=10.0, stream_count=8, simulate=True)

        # Verify inference benchmark mode command dispatched via IPC
        mock_inf_cmd.assert_called_with("set_benchmark_mode", enabled=True)

        # Verify multi-stream switch command dispatched via IPC
        mock_src_cmd.assert_called_with(
            "switch_source",
            source_type="multi_stream",
            stream_count=8,
            file_paths=None,
            buffer_size_per_stream=15,
            unthrottled=True,
        )

        # Stop Workload
        svc.stop_workload()

        # Verify nominal restoration commands dispatched via IPC
        assert any(c[0] == ("set_benchmark_mode",) and c[1].get("enabled") is False for c in mock_inf_cmd.call_args_list)
        assert any(c[0] == ("switch_source",) and c[1].get("source_type") == "file" for c in mock_src_cmd.call_args_list)


def test_workload_high_concurrency_stream_options(workload_env):
    src_mgr = workload_env["src_mgr"]
    inf_svc = workload_env["inf_svc"]
    tel_svc = workload_env["tel_svc"]
    evt_svc = workload_env["evt_svc"]
    engine = workload_env["engine"]

    svc = WorkloadService(
        source_manager=src_mgr,
        inference_service=inf_svc,
        telemetry_service=tel_svc,
        event_service=evt_svc,
        trajectory_engine=engine,
    )

    for streams in (12, 16, 20):
        status = svc.start_workload(
            workload_type="B",
            duration_seconds=5.0,
            stream_count=streams,
            simulate=True,
        )
        assert status["stream_count"] == streams
        svc.stop_workload()


