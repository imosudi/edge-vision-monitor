"""
Image preprocessing for YOLO11 and Hailo accelerator.
Includes aspect-ratio preserving letterboxing, colour space conversion,
and coordinate transformation metadata tracking.
"""

from __future__ import annotations

import time
from typing import Tuple
import cv2
import numpy as np


def letterbox_image(
    image: np.ndarray,
    target_shape: Tuple[int, int] = (640, 640),
    color: Tuple[int, int, int] = (114, 114, 114),
) -> Tuple[np.ndarray, float, Tuple[int, int]]:
    """
    Resize image to target shape (height, width) with aspect ratio preservation
    and centered padding.

    Returns:
        padded_image: Resized and padded image.
        scale: Scaling factor applied to original image.
        (pad_left, pad_top): Integer pixel offsets of padding.
    """
    target_h, target_w = target_shape
    orig_h, orig_w = image.shape[:2]

    # Calculate scale factor
    scale = min(target_w / orig_w, target_h / orig_h)
    new_w = int(round(orig_w * scale))
    new_h = int(round(orig_h * scale))

    # Resize image using bilinear interpolation
    if (orig_w, orig_h) != (new_w, new_h):
        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    else:
        resized = image

    # Compute padding
    pad_w = target_w - new_w
    pad_h = target_h - new_h
    pad_left = pad_w // 2
    pad_right = pad_w - pad_left
    pad_top = pad_h // 2
    pad_bottom = pad_h - pad_top

    # Pad with solid colour
    padded = cv2.copyMakeBorder(
        resized,
        pad_top,
        pad_bottom,
        pad_left,
        pad_right,
        cv2.BORDER_CONSTANT,
        value=color,
    )

    return padded, scale, (pad_left, pad_top)


def preprocess_frame(
    frame: np.ndarray,
    input_height: int = 640,
    input_width: int = 640,
    to_rgb: bool = True,
) -> Tuple[np.ndarray, float, Tuple[int, int], float]:
    """
    Full preprocessing pipeline from raw OpenCV BGR frame to Hailo model input tensor.

    Returns:
        tensor: Ready-to-infer input array (typically uint8 RGB in NHWC shape).
        scale: Aspect scale factor.
        pads: (pad_left, pad_top) pixel offsets.
        duration_ms: Monotonic execution duration in milliseconds.
    """
    t0 = time.monotonic()

    # Apply letterboxing
    padded, scale, pads = letterbox_image(frame, target_shape=(input_height, input_width))

    # Convert BGR to RGB
    if to_rgb:
        rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
    else:
        rgb = padded

    # Add batch dimension: [1, H, W, C]
    tensor = np.expand_dims(rgb, axis=0)

    duration_ms = (time.monotonic() - t0) * 1000.0
    return tensor, scale, pads, duration_ms
