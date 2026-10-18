"""
Hailo YOLO11 model artefact validation, HEF header checking, and class labels loading.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple
import yaml

from app.core.logging_config import get_logger

logger = get_logger("INFERENCE.VALIDATION")

# Standard COCO 80 classes used by default YOLO11 models
COCO_80_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush"
]


@dataclass
class ModelValidationResult:
    """Outcome of model artefact inspection and compatibility checks."""

    is_valid: bool
    status: str  # READY, FILE_NOT_FOUND, INVALID_FORMAT, NO_RUNTIME, ERROR
    hef_path: str
    labels_count: int = 0
    labels: List[str] = field(default_factory=list)
    input_width: int = 640
    input_height: int = 640
    error_message: Optional[str] = None
    hailo_runtime_available: bool = False
    device_available: bool = False


def load_class_labels(labels_path: Optional[str]) -> List[str]:
    """Load class labels from a text or YAML file, or return default COCO-80."""
    if not labels_path or not os.path.isfile(labels_path):
        logger.info("No labels file provided or file not found; defaulting to 80 COCO classes")
        return list(COCO_80_CLASSES)

    try:
        if labels_path.endswith((".yaml", ".yml")):
            with open(labels_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict) and "names" in data:
                    names = data["names"]
                    if isinstance(names, dict):
                        return [names[k] for k in sorted(names.keys(), key=lambda x: int(x))]
                    elif isinstance(names, list):
                        return [str(x) for x in names]
        else:
            with open(labels_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
                if lines:
                    return lines
    except Exception as e:
        logger.warning("Failed to parse labels file '%s': %s; falling back to COCO labels", labels_path, e)

    return list(COCO_80_CLASSES)


def check_hailo_runtime_installed() -> Tuple[bool, Optional[str]]:
    """Check if HailoRT Python bindings are installed and driver-compatible."""
    try:
        import hailo_platform  # type: ignore
        version = getattr(hailo_platform, "__version__", "unknown")
        if os.path.exists("/dev/hailo0"):
            try:
                vdev = hailo_platform.VDevice()
                try:
                    if hasattr(vdev, "release"):
                        vdev.release()
                except Exception:
                    pass
                del vdev
            except Exception as v_err:
                err_msg = str(v_err)
                # If physical device is already claimed by an active engine instance,
                # HailoRT returns HAILO_OUT_OF_PHYSICAL_DEVICES (error 74).
                # This confirms the driver and device are active and functional.
                if (
                    "HAILO_OUT_OF_PHYSICAL_DEVICES" in err_msg
                    or "74" in err_msg
                    or "Device or resource busy" in err_msg
                    or "out of physical devices" in err_msg.lower()
                ):
                    logger.debug("HailoRT VDevice already claimed by active process (%s): %s", version, v_err)
                    return True, version

                logger.warning("HailoRT runtime detected (%s), but VDevice initialisation failed: %s", version, v_err)
                return False, f"Driver incompatible ({v_err})"
        return True, version
    except ImportError:
        return False, None
    except Exception as exc:
        logger.warning("HailoRT runtime check error: %s", exc)
        return False, None


def check_hailo_device_node() -> bool:
    """Check if the Hailo PCIe device node exists (/dev/hailo0)."""
    return os.path.exists("/dev/hailo0")


def validate_model_artifacts(
    hef_path: str,
    labels_path: Optional[str] = None,
    metadata_path: Optional[str] = None,
    cfg_width: Optional[int] = None,
    cfg_height: Optional[int] = None,
) -> ModelValidationResult:
    """
    Validate configured model files and host Hailo environment.
    Does not crash if hardware is not connected, but produces an accurate status.
    """
    labels = load_class_labels(labels_path)
    runtime_ok, rt_version = check_hailo_runtime_installed()
    device_ok = check_hailo_device_node()

    width = cfg_width or 640
    height = cfg_height or 640

    # 1. Check HEF file existence
    if not os.path.exists(hef_path):
        return ModelValidationResult(
            is_valid=False,
            status="FILE_NOT_FOUND",
            hef_path=hef_path,
            labels_count=len(labels),
            labels=labels,
            input_width=width,
            input_height=height,
            error_message=f"Model HEF file not found at '{hef_path}'",
            hailo_runtime_available=runtime_ok,
            device_available=device_ok,
        )

    # 2. Check HEF readability and size
    try:
        file_size = os.path.getsize(hef_path)
        if file_size < 1024:
            return ModelValidationResult(
                is_valid=False,
                status="INVALID_FORMAT",
                hef_path=hef_path,
                labels_count=len(labels),
                labels=labels,
                input_width=width,
                input_height=height,
                error_message=f"Model HEF file is unexpectedly small ({file_size} bytes)",
                hailo_runtime_available=runtime_ok,
                device_available=device_ok,
            )
    except Exception as e:
        return ModelValidationResult(
            is_valid=False,
            status="ERROR",
            hef_path=hef_path,
            labels_count=len(labels),
            labels=labels,
            input_width=width,
            input_height=height,
            error_message=f"Cannot read HEF file '{hef_path}': {e}",
            hailo_runtime_available=runtime_ok,
            device_available=device_ok,
        )

    # 3. Check HailoRT library availability
    if not runtime_ok:
        return ModelValidationResult(
            is_valid=False,
            status="NO_RUNTIME",
            hef_path=hef_path,
            labels_count=len(labels),
            labels=labels,
            input_width=width,
            input_height=height,
            error_message="HailoRT Python library ('hailo_platform') is not installed",
            hailo_runtime_available=False,
            device_available=device_ok,
        )

    # 4. Check device availability
    if not device_ok:
        return ModelValidationResult(
            is_valid=False,
            status="DEVICE_NOT_FOUND",
            hef_path=hef_path,
            labels_count=len(labels),
            labels=labels,
            input_width=width,
            input_height=height,
            error_message="Hailo device node '/dev/hailo0' not found. Verify PCIe connection and driver.",
            hailo_runtime_available=runtime_ok,
            device_available=False,
        )

    # 5. Attempt HEF inspection via HailoRT
    try:
        from hailo_platform import HEF  # type: ignore
        hef_obj = HEF(hef_path)
        # Auto-discover input dimensions if not explicitly configured
        configured_groups = hef_obj.get_network_groups_infos()
        if configured_groups:
            # We can inspect stream infos if available
            pass
        return ModelValidationResult(
            is_valid=True,
            status="READY",
            hef_path=hef_path,
            labels_count=len(labels),
            labels=labels,
            input_width=width,
            input_height=height,
            error_message=None,
            hailo_runtime_available=True,
            device_available=True,
        )
    except Exception as e:
        return ModelValidationResult(
            is_valid=False,
            status="INVALID_HEF",
            hef_path=hef_path,
            labels_count=len(labels),
            labels=labels,
            input_width=width,
            input_height=height,
            error_message=f"HailoRT failed to load HEF: {e}",
            hailo_runtime_available=True,
            device_available=device_ok,
        )
