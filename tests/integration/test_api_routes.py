"""
Integration tests for FastAPI REST routes using TestClient.
"""

import pytest
from fastapi.testclient import TestClient

from app import __version__
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
    assert data["version"] == __version__


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

    start_res = client.post("/api/v1/inference/start?reset_history=false")
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


def test_video_browser_source_and_frame_endpoint(client):
    import cv2
    import numpy as np

    # 1. Sources catalogue reports browser_camera_supported
    res = client.get("/api/v1/video/sources")
    assert res.status_code == 200
    assert res.json().get("browser_camera_supported") is True

    # 2. Switch to browser source
    switch_res = client.post(
        "/api/v1/video/source",
        json={"source_type": "browser", "width": 640, "height": 480, "fps": 20},
    )
    assert switch_res.status_code == 200
    assert switch_res.json()["source_info"]["active_type"] == "browser"

    # 3. Post a browser frame
    dummy_img = np.zeros((480, 640, 3), dtype=np.uint8)
    _, jpg = cv2.imencode(".jpg", dummy_img)
    frame_res = client.post(
        "/api/v1/video/browser-frame",
        content=jpg.tobytes(),
        headers={"Content-Type": "image/jpeg"},
    )
    assert frame_res.status_code == 200
    assert frame_res.json()["status"] == "ok"
    assert frame_res.json()["frame_seq"] >= 1


def test_workload_api_lifecycle(client):
    # 1. Initial status check
    st_res = client.get("/api/v1/workload/status")
    assert st_res.status_code == 200
    st_data = st_res.json()
    assert "active" in st_data
    assert "state" in st_data

    # 2. Start Workload A via API
    start_res = client.post(
        "/api/v1/workload/start",
        json={
            "workload_type": "A",
            "duration_seconds": 10.0,
            "buffer_size": 20,
        },
    )
    assert start_res.status_code == 200
    start_data = start_res.json()
    assert start_data["active"] is True
    assert start_data["workload_type"] == "A"
    session_id = start_data.get("session_id")

    # 3. Status during execution
    active_st = client.get("/api/v1/workload/status")
    assert active_st.status_code == 200
    assert active_st.json()["active"] is True

    # 4. Stop Workload
    stop_res = client.post("/api/v1/workload/stop?reason=Integration+Test")
    assert stop_res.status_code == 200
    assert stop_res.json()["stopped"] is True

    # 5. Export CSV trajectory
    csv_res = client.get(f"/api/v1/workload/export?session_id={session_id}&format=csv")
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers.get("content-type", "")

    # 6. Export JSON trajectory
    json_res = client.get(f"/api/v1/workload/export?session_id={session_id}&format=json")
    assert json_res.status_code == 200
    assert "application/json" in json_res.headers.get("content-type", "")

    # 7. Session history check
    sess_res = client.get("/api/v1/workload/sessions")
    assert sess_res.status_code == 200
    assert isinstance(sess_res.json(), list)



