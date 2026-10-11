"""
YOLO11 post-processing, bounding box decoding, Non-Maximum Suppression (NMS),
coordinate unletterboxing, and preview frame annotation.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple
import cv2
import numpy as np

from app.inference.detection import BoundingBox, Detection


def compute_iou(box1: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    """
    Vectorised Intersection-over-Union between box1 [4] and multiple boxes [N, 4].
    Format: [xmin, ymin, xmax, ymax].
    """
    x1 = np.maximum(box1[0], boxes[:, 0])
    y1 = np.maximum(box1[1], boxes[:, 1])
    x2 = np.minimum(box1[2], boxes[:, 2])
    y2 = np.minimum(box1[3], boxes[:, 3])

    intersection = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    box1_area = (box1[2] - box1[0]) * (box1[3] - box1[1])
    boxes_area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    union = box1_area + boxes_area - intersection

    return np.where(union > 0, intersection / union, 0.0)


def non_max_suppression(
    boxes: np.ndarray,
    scores: np.ndarray,
    iou_threshold: float = 0.45,
    max_detections: int = 100,
) -> List[int]:
    """
    Standard greedy Non-Maximum Suppression.

    Args:
        boxes: Array of shape [N, 4] in (xmin, ymin, xmax, ymax).
        scores: Array of shape [N] with confidence scores.
        iou_threshold: IoU overlap threshold.
        max_detections: Maximum detections to retain.

    Returns:
        List of selected indices.
    """
    if len(boxes) == 0:
        return []

    order = scores.argsort()[::-1]
    keep = []

    while order.size > 0 and len(keep) < max_detections:
        i = order[0]
        keep.append(int(i))
        if order.size == 1:
            break

        remaining_boxes = boxes[order[1:]]
        ious = compute_iou(boxes[i], remaining_boxes)
        mask = ious <= iou_threshold
        order = order[1:][mask]

    return keep


def unletterbox_box(
    xmin: float,
    ymin: float,
    xmax: float,
    ymax: float,
    scale: float,
    pad_left: int,
    pad_top: int,
    orig_w: int,
    orig_h: int,
) -> BoundingBox:
    """
    Transform bounding box coordinates from letterboxed frame back to original image dimensions,
    returning normalised [0, 1] coordinates.
    """
    # Remove padding
    real_x1 = (xmin - pad_left) / scale
    real_y1 = (ymin - pad_top) / scale
    real_x2 = (xmax - pad_left) / scale
    real_y2 = (ymax - pad_top) / scale

    # Normalise by original image dimensions
    norm_x1 = max(0.0, min(1.0, real_x1 / orig_w))
    norm_y1 = max(0.0, min(1.0, real_y1 / orig_h))
    norm_x2 = max(0.0, min(1.0, real_x2 / orig_w))
    norm_y2 = max(0.0, min(1.0, real_y2 / orig_h))

    return BoundingBox(xmin=norm_x1, ymin=norm_y1, xmax=norm_x2, ymax=norm_y2)


def decode_hailo_heads(
    outputs: Dict[str, Any],
    num_classes: int = 80,
    strides: Tuple[int, ...] = (8, 16, 32),
    reg_max: int = 16,
) -> Optional[np.ndarray]:
    """
    Decodes the 6 detection head convolution tensors from Hailo-8L YOLO11 graph.
    Returns array of shape [N_anchors, 4 + num_classes] where columns 0:4 are [x1, y1, x2, y2]
    in letterbox coordinates (640x640), and columns 4: are class probabilities.
    """
    tensors_by_res: Dict[int, Dict[str, np.ndarray]] = {}
    dfl_weights = np.arange(reg_max, dtype=np.float32)

    for name, arr in outputs.items():
        if not isinstance(arr, np.ndarray):
            continue
        s = arr.shape
        if len(s) == 4 and s[0] == 1:
            h, w, c = s[1], s[2], s[3]
            data = arr[0]
        elif len(s) == 3:
            h, w, c = s[0], s[1], s[2]
            data = arr
        elif len(s) == 4 and s[1] in (64, num_classes):
            data = arr[0].transpose(1, 2, 0)
            h, w, c = data.shape
        else:
            continue

        if h not in tensors_by_res:
            tensors_by_res[h] = {}

        if c == 4 * reg_max or c == 64:
            tensors_by_res[h]["box"] = data
        elif c == num_classes or c > 1:
            tensors_by_res[h]["cls"] = data

    all_boxes: List[np.ndarray] = []
    all_scores: List[np.ndarray] = []
    expected_resolutions = [640 // s for s in strides]

    for stride, exp_res in zip(strides, expected_resolutions):
        if exp_res not in tensors_by_res:
            continue
        res_dict = tensors_by_res[exp_res]
        if "box" not in res_dict or "cls" not in res_dict:
            continue

        box_nhwc = res_dict["box"]  # (H, W, 64)
        cls_nhwc = res_dict["cls"]  # (H, W, nc)
        h, w = box_nhwc.shape[:2]

        # 1. Class probabilities: sigmoid
        cls_scores = 1.0 / (1.0 + np.exp(-np.clip(cls_nhwc, -20.0, 20.0)))
        cls_scores = cls_scores.reshape(-1, num_classes)
        all_scores.append(cls_scores)

        # 2. Box regression: DFL softmax + expectation
        box_reshaped = box_nhwc.reshape(-1, 4, reg_max)  # (N_anchors, 4, 16)
        max_val = np.max(box_reshaped, axis=-1, keepdims=True)
        exp_val = np.exp(box_reshaped - max_val)
        softmax = exp_val / np.sum(exp_val, axis=-1, keepdims=True)
        dist = np.sum(softmax * dfl_weights, axis=-1)  # (N_anchors, 4): l, t, r, b

        # 3. Anchor points grid
        xv, yv = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
        anchor_points = np.stack([xv + 0.5, yv + 0.5], axis=-1).reshape(-1, 2)

        lt = dist[:, :2]  # left, top
        rb = dist[:, 2:]  # right, bottom

        x1y1 = (anchor_points - lt) * float(stride)
        x2y2 = (anchor_points + rb) * float(stride)

        xyxy = np.concatenate([x1y1, x2y2], axis=-1)
        all_boxes.append(xyxy)

    if not all_boxes or not all_scores:
        return None

    concat_boxes = np.concatenate(all_boxes, axis=0)
    concat_scores = np.concatenate(all_scores, axis=0)
    return np.concatenate([concat_boxes, concat_scores], axis=1)


def decode_yolo11_detections(
    raw_outputs: Any,
    orig_w: int,
    orig_h: int,
    scale: float,
    pad_offsets: Tuple[int, int],
    labels: List[str],
    confidence_threshold: float = 0.25,
    nms_iou_threshold: float = 0.45,
    max_detections: int = 100,
) -> Tuple[List[Detection], float]:
    """
    Decodes inference outputs into structured detections.
    Supports Hailo 6-head convolution tensors, Hailo pre-NMS output format,
    and raw YOLO output tensors.
    """
    t0 = time.monotonic()
    detections: List[Detection] = []
    pad_left, pad_top = pad_offsets

    if raw_outputs is None:
        return [], 0.0

    # Case 1: Dict output (Hailo NMS format or Hailo 6-head raw tensors)
    if isinstance(raw_outputs, dict):
        has_list = any(isinstance(v, list) for v in raw_outputs.values())
        if has_list:
            for name, tensor in raw_outputs.items():
                if isinstance(tensor, list):
                    for class_idx, class_detections in enumerate(tensor):
                        if len(class_detections) == 0:
                            continue
                        class_name = labels[class_idx] if class_idx < len(labels) else f"class_{class_idx}"
                        for det in class_detections:
                            if len(det) >= 5:
                                ymin, xmin, ymax, xmax, score = det[:5]
                                if score >= confidence_threshold:
                                    box = unletterbox_box(
                                        xmin, ymin, xmax, ymax, scale, pad_left, pad_top, orig_w, orig_h
                                    )
                                    detections.append(
                                        Detection(
                                            box=box,
                                            class_id=class_idx,
                                            class_name=class_name,
                                            confidence=float(score),
                                        )
                                    )
            detections.sort(key=lambda d: d.confidence, reverse=True)
            detections = detections[:max_detections]
        else:
            # Multi-head Hailo convolution outputs
            hailo_arr = decode_hailo_heads(raw_outputs, num_classes=len(labels))
            if hailo_arr is not None and len(hailo_arr) > 0:
                boxes_xyxy = hailo_arr[:, :4]
                class_scores = hailo_arr[:, 4:]
                class_ids = np.argmax(class_scores, axis=1)
                confidences = np.max(class_scores, axis=1)

                mask = confidences >= confidence_threshold
                valid_boxes = boxes_xyxy[mask]
                valid_conf = confidences[mask]
                valid_ids = class_ids[mask]

                if len(valid_boxes) > 0:
                    keep_indices = non_max_suppression(
                        valid_boxes, valid_conf, iou_threshold=nms_iou_threshold, max_detections=max_detections
                    )
                    for idx in keep_indices:
                        b = valid_boxes[idx]
                        cid = int(valid_ids[idx])
                        score = float(valid_conf[idx])
                        cname = labels[cid] if cid < len(labels) else f"class_{cid}"
                        box = unletterbox_box(
                            b[0], b[1], b[2], b[3], scale, pad_left, pad_top, orig_w, orig_h
                        )
                        detections.append(
                            Detection(
                                box=box,
                                class_id=cid,
                                class_name=cname,
                                confidence=score,
                            )
                        )

    # Case 2: Numpy array output (Raw YOLO head, e.g., shape [1, 84, 8400] or [1, 8400, 84])
    elif isinstance(raw_outputs, np.ndarray):
        arr = np.squeeze(raw_outputs)  # shape could be [84, 8400] or [8400, 84]
        if arr.ndim == 2:
            if arr.shape[0] < arr.shape[1] and arr.shape[0] > 4:
                arr = arr.T  # Transpose to [N_anchors, 4 + N_classes]

            boxes_xywh = arr[:, :4]
            class_scores = arr[:, 4:]
            class_ids = np.argmax(class_scores, axis=1)
            confidences = np.max(class_scores, axis=1)

            # Filter by confidence
            mask = confidences >= confidence_threshold
            valid_boxes = boxes_xywh[mask]
            valid_conf = confidences[mask]
            valid_ids = class_ids[mask]

            if len(valid_boxes) > 0:
                # Convert xywh to xyxy
                cx = valid_boxes[:, 0]
                cy = valid_boxes[:, 1]
                w = valid_boxes[:, 2]
                h = valid_boxes[:, 3]
                x1 = cx - w / 2.0
                y1 = cy - h / 2.0
                x2 = cx + w / 2.0
                y2 = cy + h / 2.0
                xyxy = np.column_stack([x1, y1, x2, y2])

                # Run NMS
                keep_indices = non_max_suppression(
                    xyxy, valid_conf, iou_threshold=nms_iou_threshold, max_detections=max_detections
                )

                for idx in keep_indices:
                    box_xyxy = xyxy[idx]
                    cid = int(valid_ids[idx])
                    score = float(valid_conf[idx])
                    cname = labels[cid] if cid < len(labels) else f"class_{cid}"
                    box = unletterbox_box(
                        box_xyxy[0],
                        box_xyxy[1],
                        box_xyxy[2],
                        box_xyxy[3],
                        scale,
                        pad_left,
                        pad_top,
                        orig_w,
                        orig_h,
                    )
                    detections.append(
                        Detection(
                            box=box,
                            class_id=cid,
                            class_name=cname,
                            confidence=score,
                        )
                    )

    duration_ms = (time.monotonic() - t0) * 1000.0
    return detections, duration_ms


# Curated modern palette for class bounding boxes
PALETTE = [
    (0, 240, 255),    # Cyan
    (121, 40, 202),   # Violet
    (16, 185, 129),   # Emerald
    (245, 158, 11),   # Amber
    (239, 68, 68),    # Rose
    (59, 130, 246),   # Royal Blue
    (236, 72, 153),   # Pink
    (14, 165, 233),   # Sky
    (34, 197, 94),    # Green
    (249, 115, 22),   # Orange
]


def annotate_frame(
    frame: np.ndarray,
    detections: List[Detection],
    draw_confidence: bool = True,
) -> np.ndarray:
    """
    Renders high-contrast, modern bounding boxes and label tags onto frame copy.
    """
    if not detections:
        return frame

    annotated = frame.copy()
    h, w = frame.shape[:2]

    for det in detections:
        x1, y1, x2, y2 = det.box.to_pixel_coords(w, h)
        color = PALETTE[det.class_id % len(PALETTE)]

        # Draw smooth rounded-like box with 2px stroke
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)

        # Label tag
        if draw_confidence:
            label_text = f"{det.class_name} {int(det.confidence * 100)}%"
        else:
            label_text = det.class_name

        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.5
        thickness = 1
        (tw, th), baseline = cv2.getTextSize(label_text, font, font_scale, thickness)

        # Draw filled background tag
        tag_y1 = max(0, y1 - th - baseline - 4)
        tag_y2 = y1
        tag_x1 = x1
        tag_x2 = min(w, x1 + tw + 8)

        cv2.rectangle(annotated, (tag_x1, tag_y1), (tag_x2, tag_y2), color, -1)
        # Dark text inside bright tag for contrast
        text_color = (15, 23, 42)
        cv2.putText(
            annotated,
            label_text,
            (tag_x1 + 4, tag_y2 - baseline),
            font,
            font_scale,
            text_color,
            thickness,
            cv2.LINE_AA,
        )

    return annotated
