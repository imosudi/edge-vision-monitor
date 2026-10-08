"""
Unit tests for preprocessing, letterboxing, and tensor generation.
"""

import numpy as np
import pytest

from app.inference.preprocessing import letterbox_image, preprocess_frame


def test_letterbox_aspect_ratio_preservation():
    # Test widescreen image 1280x720 resized to 640x640
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    padded, scale, (pad_left, pad_top) = letterbox_image(img, target_shape=(640, 640))

    assert padded.shape == (640, 640, 3)
    assert scale == 0.5  # 1280 * 0.5 = 640
    assert pad_left == 0
    # 720 * 0.5 = 360; (640 - 360) / 2 = 140 top padding
    assert pad_top == 140


def test_preprocess_frame_pipeline():
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    tensor, scale, pads, duration_ms = preprocess_frame(img, input_height=640, input_width=640, to_rgb=True)

    assert tensor.shape == (1, 640, 640, 3)
    assert tensor.dtype == np.uint8
    assert duration_ms >= 0.0
    assert scale == 1.0  # 640 / 640
    assert pads == (0, 80)
