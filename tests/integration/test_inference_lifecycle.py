"""
Integration tests for complete ApplicationLifecycleManager startup, execution, and graceful shutdown.
"""

import time
from app.core.config import AppConfig, ModelConfig, ServerConfig, StorageConfig, VideoSourceConfig
from app.core.lifecycle import ApplicationLifecycleManager


def test_full_application_lifecycle_execution(temp_dir):
    cfg = AppConfig(
        model=ModelConfig(
            hef_path="models/yolo11n.hef",
            labels_path=None,
        ),
        video=VideoSourceConfig(
            default_source_type="file",
            media_dir=temp_dir,
            video_file_path=None,
        ),
        storage=StorageConfig(
            db_path=f"{temp_dir}/lifecycle_test.db",
            batch_size=5,
            flush_interval_seconds=0.1,
        ),
        server=ServerConfig(
            host="127.0.0.1",
            port=8000,
            log_level="DEBUG",
        ),
    )

    lifecycle = ApplicationLifecycleManager(config=cfg)
    lifecycle.startup()

    # Allow workers to run and process several frames
    time.sleep(0.5)

    assert lifecycle.telemetry_service.get_status()["active"] is True
    assert lifecycle.inference_service.is_running() is True
    assert lifecycle.inference_service.get_stats()["total_frames_processed"] > 0

    # Ensure clean shutdown
    lifecycle.shutdown()
    assert lifecycle.inference_service.is_running() is False
    assert lifecycle.telemetry_service.get_status()["active"] is False
