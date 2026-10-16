"""
Unit tests for shared-memory (/dev/shm) IPC coordination layer.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from app.core import ipc


def test_ipc_telemetry_publish_and_get(tmp_path: Path):
    with patch.object(ipc, "SHM_DIR", tmp_path), \
         patch.object(ipc, "TELEMETRY_METRICS_FILE", tmp_path / "evm_telemetry_latest.json"), \
         patch.object(ipc, "TELEMETRY_CATALOG_FILE", tmp_path / "evm_telemetry_catalog.json"), \
         patch.object(ipc, "TELEMETRY_STATUS_FILE", tmp_path / "evm_telemetry_status.json"):

        metrics = {"cpu_temp_c": 45.2, "ram_usage_percent": 30.5}
        catalog = [{"name": "cpu_temp_c", "unit": "°C"}]
        status = {"active": True, "active_alarms_count": 0}

        ipc.publish_telemetry_snapshot(metrics, catalog=catalog, status=status)

        read_metrics = ipc.get_ipc_telemetry_metrics()
        assert read_metrics["cpu_temp_c"] == 45.2

        read_catalog = ipc.get_ipc_telemetry_catalog()
        assert len(read_catalog) == 1
        assert read_catalog[0]["name"] == "cpu_temp_c"

        read_status = ipc.get_ipc_telemetry_status()
        assert read_status["active"] is True


def test_ipc_inference_publish_and_get(tmp_path: Path):
    with patch.object(ipc, "SHM_DIR", tmp_path), \
         patch.object(ipc, "INFERENCE_LATEST_FILE", tmp_path / "evm_inference_latest.json"), \
         patch.object(ipc, "ENGINE_STATUS_FILE", tmp_path / "evm_engine_status.json"), \
         patch.object(ipc, "PREVIEW_JPEG_FILE", tmp_path / "evm_latest_preview.jpg"):

        fake_jpeg = b"\xff\xd8\xff\xe0fakejpeg"
        detections = [{"class_name": "person", "confidence": 0.88, "bbox": [10, 10, 50, 50]}]
        stats = {"current_fps": 28.5, "active_backend": "hailo", "is_running": True}

        ipc.publish_inference_frame(fake_jpeg, detections, stats, frame_seq=42)
        ipc.publish_engine_status({"backend": "hailo", "ready": True, "type": "Hailo-8L"})

        assert ipc.get_ipc_latest_jpeg() == fake_jpeg

        det_data = ipc.get_ipc_latest_detections()
        assert det_data["count"] == 1
        assert det_data["detections"][0]["class_name"] == "person"

        read_stats = ipc.get_ipc_inference_stats()
        assert read_stats["current_fps"] == 28.5

        eng_st = ipc.get_ipc_engine_status()
        assert eng_st["backend"] == "hailo"
        assert eng_st["ready"] is True


def test_ipc_source_commands(tmp_path: Path):
    with patch.object(ipc, "SHM_DIR", tmp_path), \
         patch.object(ipc, "SOURCE_COMMAND_FILE", tmp_path / "evm_source_command.json"), \
         patch.object(ipc, "SOURCE_STATUS_FILE", tmp_path / "evm_source_status.json"), \
         patch.object(ipc, "SOURCE_CATALOG_FILE", tmp_path / "evm_source_catalog.json"):

        ipc.publish_source_status({"source_id": "picamera:0", "active_type": "picamera"}, {"csi_camera_supported": True})
        st = ipc.get_ipc_source_status()
        assert st["active_type"] == "picamera"
        cat = ipc.get_ipc_source_catalog()
        assert cat["csi_camera_supported"] is True

        ipc.send_ipc_source_command("switch_source", source_type="usb", device="/dev/video0")
        cmd = ipc.consume_ipc_source_command()
        assert cmd is not None
        assert cmd["command"] == "switch_source"
        assert cmd["kwargs"]["source_type"] == "usb"

        # Ensure consumed command unlinks file so next read is None
        assert ipc.consume_ipc_source_command() is None


def test_ipc_raw_frame_buffer(tmp_path: Path):
    with patch.object(ipc, "SHM_DIR", tmp_path), \
         patch.object(ipc, "RAW_FRAME_BIN_FILE", tmp_path / "evm_raw_frame.bin"), \
         patch.object(ipc, "RAW_FRAME_META_FILE", tmp_path / "evm_raw_frame.json"):

        raw_bytes = b"abcdef123456"
        ipc.publish_raw_frame(raw_bytes, width=2, height=2, channels=3, frame_seq=7, source_id="test:cam")

        frame = ipc.get_ipc_raw_frame()
        assert frame is not None
        data, meta = frame
        assert data == raw_bytes
        assert meta["frame_seq"] == 7
        assert meta["width"] == 2
