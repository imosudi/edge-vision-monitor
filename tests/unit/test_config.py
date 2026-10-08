"""
Unit tests for configuration loading, validation, and environment overrides.
"""

import os
import pytest
from pydantic import ValidationError

from app.core.config import AppConfig, ModelConfig, load_config


def test_default_config_initialisation():
    cfg = AppConfig()
    assert cfg.model.confidence_threshold == 0.25
    assert cfg.model.nms_iou_threshold == 0.45
    assert cfg.storage.retention_days == 7
    assert cfg.server.port == 8000
    assert cfg.server.host == "127.0.0.1"


def test_invalid_confidence_threshold_rejected():
    with pytest.raises(ValidationError):
        ModelConfig(confidence_threshold=1.5)

    with pytest.raises(ValidationError):
        ModelConfig(confidence_threshold=-0.1)


def test_invalid_port_rejected():
    with pytest.raises(ValidationError):
        AppConfig(server={"port": 80})  # below 1024


def test_public_config_redaction():
    cfg = AppConfig()
    pub = cfg.get_public_config()
    assert "model" in pub
    assert "video" in pub
    assert "telemetry" in pub
    assert pub["server"]["port"] == 8000


def test_env_override(monkeypatch, temp_dir):
    monkeypatch.setenv("EVM_SERVER__PORT", "9090")
    monkeypatch.setenv("EVM_MODEL__CONFIDENCE_THRESHOLD", "0.6")
    monkeypatch.setenv("EVM_TELEMETRY__ENABLE_INA219", "true")

    cfg = load_config()
    assert cfg.server.port == 9090
    assert cfg.model.confidence_threshold == 0.6
    assert cfg.telemetry.enable_ina219 is True
