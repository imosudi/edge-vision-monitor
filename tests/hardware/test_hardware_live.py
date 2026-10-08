"""
Hardware-dependent verification tests for Raspberry Pi 5 + Hailo-8L.
Skips cleanly if hardware devices are not detected.
"""

import os
import pytest

from app.core.config import ModelConfig
from app.inference.engine import HailoInferenceEngine
from app.inference.model_validation import check_hailo_device_node, check_hailo_runtime_installed


@pytest.mark.skipif(not check_hailo_device_node(), reason="Hailo-8L device node /dev/hailo0 not present")
def test_hailo_device_presence():
    assert os.path.exists("/dev/hailo0")


@pytest.mark.skipif(not check_hailo_runtime_installed()[0], reason="HailoRT Python bindings not installed")
def test_hailort_importable():
    import hailo_platform  # type: ignore
    assert hasattr(hailo_platform, "VDevice")


@pytest.mark.skipif(
    not (check_hailo_device_node() and os.path.isfile("models/yolo11n.hef")),
    reason="Physical Hailo-8L or models/yolo11n.hef not present",
)
def test_live_hailo_inference():
    cfg = ModelConfig(hef_path="models/yolo11n.hef")
    engine = HailoInferenceEngine(cfg)
    val = engine.initialize()
    assert val.is_valid is True
    engine.close()
