"""
Unit tests for post-processing, IoU, NMS, unletterboxing, and frame annotation.
"""

import numpy as np
import pytest

from app.inference.detection import BoundingBox, Detection
from app.inference.postprocessing import (
    annotate_frame,
    compute_iou,
    decode_yolo11_detections,
    non_max_suppression,
    unletterbox_box,
)


def test_compute_iou_identical_and_disjoint():
    box1 = np.array([10.0, 10.0, 50.0, 50.0])
    boxes = np.array([
        [10.0, 10.0, 50.0, 50.0],  # Identical
        [60.0, 60.0, 100.0, 100.0],  # Disjoint
    ])
    ious = compute_iou(box1, boxes)
    assert pytest.approx(ious[0], 0.001) == 1.0
    assert pytest.approx(ious[1], 0.001) == 0.0


def test_non_max_suppression_suppresses_overlapping():
    boxes = np.array([
        [10.0, 10.0, 50.0, 50.0],
        [12.0, 12.0, 50.0, 50.0],  # High overlap
        [100.0, 100.0, 200.0, 200.0],  # Independent
    ])
    scores = np.array([0.9, 0.85, 0.95])
    keep = non_max_suppression(boxes, scores, iou_threshold=0.45)
    assert len(keep) == 2
    assert 2 in keep  # score 0.95
    assert 0 in keep  # score 0.90


def test_unletterbox_box_inversion():
    # Target frame was 640x640 with scale=0.5, pad_left=0, pad_top=140
    # A box located in the unpadded area: x=[100, 200], y=[240, 340]
    box = unletterbox_box(
        xmin=100, ymin=240, xmax=200, ymax=340,
        scale=0.5, pad_left=0, pad_top=140,
        orig_w=1280, orig_h=720
    )
    # real_x1 = 100 / 0.5 = 200; norm = 200 / 1280 = 0.15625
    # real_y1 = (240 - 140) / 0.5 = 200; norm = 200 / 720 = 0.27777
    assert pytest.approx(box.xmin, 0.01) == 0.156
    assert pytest.approx(box.ymin, 0.01) == 0.277


def test_annotate_frame_renders():
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    det = Detection(
        box=BoundingBox(xmin=0.1, ymin=0.1, xmax=0.5, ymax=0.5),
        class_id=0,
        class_name="person",
        confidence=0.88,
    )
    annotated = annotate_frame(img, [det])
    assert annotated.shape == (480, 640, 3)
    assert np.any(annotated > 0)  # Has rendered pixels
