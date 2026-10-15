"""
Pytest fixtures and test environment configuration.
"""

import os
import shutil
import tempfile
import pytest

from app.core.config import AppConfig, ModelConfig, ServerConfig, StorageConfig, VideoSourceConfig
from app.storage.repository import TelemetryRepository


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def test_config(temp_dir):
    db_path = os.path.join(temp_dir, "test_telemetry.db")
    media_dir = os.path.join(temp_dir, "media")
    os.makedirs(media_dir, exist_ok=True)

    cfg = AppConfig(
        model=ModelConfig(
            hef_path="models/yolo11n.hef",
            labels_path=None,
            confidence_threshold=0.25,
            nms_iou_threshold=0.45,
        ),
        video=VideoSourceConfig(
            default_source_type="file",
            media_dir=media_dir,
            video_file_path=None,
        ),
        storage=StorageConfig(
            db_path=db_path,
            batch_size=5,
            flush_interval_seconds=0.1,
            retention_days=1,
        ),
        server=ServerConfig(
            host="127.0.0.1",
            port=8000,
            log_level="DEBUG",
        ),
    )
    return cfg


@pytest.fixture
def test_repo(test_config):
    repo = TelemetryRepository(
        db_path=test_config.storage.db_path,
        batch_size=test_config.storage.batch_size,
        flush_interval_seconds=test_config.storage.flush_interval_seconds,
    )
    repo.start()
    yield repo
    repo.stop()


@pytest.fixture(autouse=True)
def clean_test_environment():
    """Ensure clean test environment by resetting environment variables."""
    yield
    os.environ.pop("EVM_SERVICE", None)
