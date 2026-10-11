"""
Integration tests for FastAPI REST routes using TestClient.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.lifecycle import get_lifecycle_manager
from app.main import create_app


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_health_endpoint(client):
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "uptime_seconds" in data
    assert data["version"] == "1.0.0"


def test_ready_endpoint(client):
    res = client.get("/api/v1/ready")
    assert res.status_code == 200
    data = res.json()
    assert "ready" in data
    assert "model_status" in data


def test_status_endpoint(client):
    res = client.get("/api/v1/status")
    assert res.status_code == 200
    data = res.json()
    assert "application_state" in data
    assert "active_source" in data


def test_metrics_endpoints(client):
    res = client.get("/api/v1/metrics/current")
    assert res.status_code == 200
    assert isinstance(res.json(), dict)

    cat_res = client.get("/api/v1/metrics/catalog")
    assert cat_res.status_code == 200
    assert isinstance(cat_res.json(), list)


def test_inference_endpoints(client):
    stats = client.get("/api/v1/inference/stats")
    assert stats.status_code == 200
    assert "is_running" in stats.json()

    dets = client.get("/api/v1/detections/latest")
    assert dets.status_code == 200
    assert "count" in dets.json()

    # Toggle stop and start
    stop_res = client.post("/api/v1/inference/stop")
    assert stop_res.status_code == 200
    assert stop_res.json()["running"] is False

    start_res = client.post("/api/v1/inference/start")
    assert start_res.status_code == 200
    assert start_res.json()["running"] is True


def test_video_sources_endpoint(client):
    res = client.get("/api/v1/video/sources")
    assert res.status_code == 200
    data = res.json()
    assert "usb_devices" in data
    assert "media_files" in data


def test_public_config_endpoint(client):
    res = client.get("/api/v1/config/public")
    assert res.status_code == 200
    data = res.json()
    assert "model" in data
    assert "video" in data


def test_system_info_endpoint(client):
    res = client.get("/api/v1/system/info")
    assert res.status_code == 200
    data = res.json()
    assert "hostname" in data
    assert "python_version" in data


def test_video_upload_endpoint(client):
    # Test valid video upload
    fake_content = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100
    files = {"file": ("test_upload.mp4", fake_content, "video/mp4")}
    res = client.post("/api/v1/video/upload", files=files)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["filename"] == "test_upload.mp4"
    assert "test_upload.mp4" in data["media_files"]

    # Test invalid extension
    invalid_files = {"file": ("malicious.sh", b"echo 1", "text/plain")}
    res_err = client.post("/api/v1/video/upload", files=invalid_files)
    assert res_err.status_code == 400

