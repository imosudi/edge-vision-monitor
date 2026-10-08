"""
Inference engine interface, HailoRT hardware accelerator execution,
and mock test engine.
"""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import numpy as np

from app.core.config import ModelConfig
from app.core.logging_config import get_logger
from app.inference.detection import BoundingBox, Detection, DetectionResult
from app.inference.model_validation import (
    ModelValidationResult,
    check_hailo_device_node,
    check_hailo_runtime_installed,
    load_class_labels,
    validate_model_artifacts,
)
from app.inference.postprocessing import decode_yolo11_detections
from app.inference.preprocessing import preprocess_frame

logger = get_logger("INFERENCE.ENGINE")


class BaseInferenceEngine(ABC):
    """Abstract interface for object detection inference execution."""

    @abstractmethod
    def initialize(self) -> ModelValidationResult:
        """Initialise accelerator, load model, and verify readiness."""
        pass

    @abstractmethod
    def infer(self, frame: np.ndarray, frame_seq: int, source_id: str) -> DetectionResult:
        """Run preprocessing, model execution, and post-processing on a video frame."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Cleanly release model and accelerator resources."""
        pass

    @abstractmethod
    def is_ready(self) -> bool:
        """Check if engine is ready for inference."""
        pass

    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        """Return engine health and readiness details."""
        pass


class HailoInferenceEngine(BaseInferenceEngine):
    """Production Hailo-8L accelerator inference engine using HailoRT."""

    def __init__(self, config: ModelConfig):
        self._config = config
        self._validation: Optional[ModelValidationResult] = None
        self._vdevice: Any = None
        self._infer_model: Any = None
        self._configured_infer_model: Any = None
        self._bindings: Any = None
        self._labels: List[str] = []
        self._is_ready: bool = False

    def initialize(self) -> ModelValidationResult:
        self._validation = validate_model_artifacts(
            hef_path=self._config.hef_path,
            labels_path=self._config.labels_path,
            metadata_path=self._config.metadata_path,
            cfg_width=self._config.input_width,
            cfg_height=self._config.input_height,
        )
        self._labels = self._validation.labels

        if not self._validation.is_valid:
            logger.warning(
                "Hailo inference engine cannot start: %s (%s)",
                self._validation.error_message,
                self._validation.status,
            )
            self._is_ready = False
            return self._validation

        try:
            from hailo_platform import VDevice, InferModel  # type: ignore

            # Create virtual device
            self._vdevice = VDevice()
            # Create inference model from HEF
            self._infer_model = self._vdevice.create_infer_model(self._config.hef_path)
            self._configured_infer_model = self._infer_model.configure()
            self._bindings = self._configured_infer_model.create_bindings()

            self._is_ready = True
            logger.info("Hailo-8L inference engine initialised successfully with HEF: %s", self._config.hef_path)
            return self._validation

        except Exception as e:
            logger.error("Failed to configure HailoRT model: %s", e, exc_info=True)
            self._is_ready = False
            self._validation.is_valid = False
            self._validation.status = "CONFIG_ERROR"
            self._validation.error_message = str(e)
            return self._validation

    def infer(self, frame: np.ndarray, frame_seq: int, source_id: str) -> DetectionResult:
        if not self._is_ready or self._configured_infer_model is None:
            return DetectionResult(
                frame_seq=frame_seq,
                source_id=source_id,
                error_status="Engine not ready",
            )

        orig_h, orig_w = frame.shape[:2]
        t_start = time.monotonic()

        # 1. Preprocess
        input_w = self._validation.input_width if self._validation else 640
        input_h = self._validation.input_height if self._validation else 640
        input_tensor, scale, pads, prep_ms = preprocess_frame(
            frame, input_height=input_h, input_width=input_w, to_rgb=True
        )

        # 2. Hailo Accelerator Execution
        t_hailo_start = time.monotonic()
        try:
            # Bind input buffer
            input_names = self._infer_model.input_names
            if input_names:
                self._bindings.input(input_names[0]).set_buffer(input_tensor)

            # Synchronous or wait-for-completion inference
            self._configured_infer_model.wait_for_async_ready(timeout_ms=1000)
            job = self._configured_infer_model.run_async([self._bindings])
            job.wait(timeout_ms=1000)

            # Retrieve outputs
            raw_outputs: Dict[str, Any] = {}
            for out_name in self._infer_model.output_names:
                raw_outputs[out_name] = self._bindings.output(out_name).get_buffer()

        except Exception as e:
            hailo_ms = (time.monotonic() - t_hailo_start) * 1000.0
            logger.error("Hailo inference execution failed: %s", e)
            return DetectionResult(
                frame_seq=frame_seq,
                source_id=source_id,
                preprocessing_ms=prep_ms,
                hailo_exec_ms=hailo_ms,
                total_latency_ms=(time.monotonic() - t_start) * 1000.0,
                error_status=str(e),
            )

        hailo_ms = (time.monotonic() - t_hailo_start) * 1000.0

        # 3. Post-process
        detections, post_ms = decode_yolo11_detections(
            raw_outputs=raw_outputs,
            orig_w=orig_w,
            orig_h=orig_h,
            scale=scale,
            pad_offsets=pads,
            labels=self._labels,
            confidence_threshold=self._config.confidence_threshold,
            nms_iou_threshold=self._config.nms_iou_threshold,
            max_detections=self._config.max_detections,
        )

        total_latency_ms = (time.monotonic() - t_start) * 1000.0

        return DetectionResult(
            frame_seq=frame_seq,
            source_id=source_id,
            monotonic_ts=time.monotonic(),
            detections=detections,
            image_width=orig_w,
            image_height=orig_h,
            preprocessing_ms=prep_ms,
            hailo_exec_ms=hailo_ms,
            postprocessing_ms=post_ms,
            total_latency_ms=total_latency_ms,
        )

    def close(self) -> None:
        self._is_ready = False
        try:
            if self._configured_infer_model:
                self._configured_infer_model = None
            if self._infer_model:
                self._infer_model = None
            if self._vdevice:
                self._vdevice.release()
                self._vdevice = None
            logger.info("Hailo inference engine resources released")
        except Exception as e:
            logger.warning("Error releasing Hailo resources: %s", e)

    def is_ready(self) -> bool:
        return self._is_ready

    def get_status(self) -> Dict[str, Any]:
        return {
            "type": "Hailo-8L",
            "ready": self._is_ready,
            "status": self._validation.status if self._validation else "UNINITIALIZED",
            "hef_path": self._config.hef_path,
            "error_message": self._validation.error_message if self._validation else None,
            "is_mock": False,
        }


class MockInferenceEngine(BaseInferenceEngine):
    """
    Mock inference engine for automated testing and local development.
    Generates deterministic simulated detections without requiring physical Hailo-8L hardware.
    """

    def __init__(self, config: ModelConfig):
        self._config = config
        self._labels = load_class_labels(config.labels_path)
        self._is_ready = False
        self._validation: Optional[ModelValidationResult] = None

    def initialize(self) -> ModelValidationResult:
        self._is_ready = True
        self._validation = ModelValidationResult(
            is_valid=True,
            status="MOCK_READY",
            hef_path=self._config.hef_path,
            labels_count=len(self._labels),
            labels=self._labels,
            input_width=self._config.input_width or 640,
            input_height=self._config.input_height or 640,
            hailo_runtime_available=False,
            device_available=False,
        )
        logger.info("Mock inference engine initialised (simulated detections for testing)")
        return self._validation

    def infer(self, frame: np.ndarray, frame_seq: int, source_id: str) -> DetectionResult:
        orig_h, orig_w = frame.shape[:2]
        t_start = time.monotonic()

        # Simulate synthetic detection moving gently across screen
        t = frame_seq * 0.1
        cx = 0.5 + 0.25 * math.sin(t)
        cy = 0.5 + 0.15 * math.cos(t)
        w, h = 0.2, 0.3

        box1 = BoundingBox(
            xmin=max(0.0, cx - w / 2),
            ymin=max(0.0, cy - h / 2),
            xmax=min(1.0, cx + w / 2),
            ymax=min(1.0, cy + h / 2),
        )
        detections = [
            Detection(
                box=box1,
                class_id=0,
                class_name=self._labels[0] if self._labels else "person",
                confidence=0.88,
            )
        ]

        # Add second detection occasionally
        if frame_seq % 2 == 0 and len(self._labels) > 2:
            box2 = BoundingBox(xmin=0.1, ymin=0.2, xmax=0.35, ymax=0.6)
            detections.append(
                Detection(
                    box=box2,
                    class_id=2,
                    class_name=self._labels[2] if len(self._labels) > 2 else "car",
                    confidence=0.74,
                )
            )

        prep_ms = 1.2
        hailo_ms = 4.8  # Typical Hailo-8L execution latency for YOLO11n
        post_ms = 0.8
        total_latency_ms = (time.monotonic() - t_start) * 1000.0 + (prep_ms + hailo_ms + post_ms)

        return DetectionResult(
            frame_seq=frame_seq,
            source_id=source_id,
            monotonic_ts=time.monotonic(),
            detections=detections,
            image_width=orig_w,
            image_height=orig_h,
            preprocessing_ms=prep_ms,
            hailo_exec_ms=hailo_ms,
            postprocessing_ms=post_ms,
            total_latency_ms=total_latency_ms,
        )

    def close(self) -> None:
        self._is_ready = False
        logger.info("Mock inference engine closed")

    def is_ready(self) -> bool:
        return self._is_ready

    def get_status(self) -> Dict[str, Any]:
        return {
            "type": "MockEngine",
            "ready": self._is_ready,
            "status": "MOCK_ACTIVE",
            "hef_path": self._config.hef_path,
            "error_message": None,
            "is_mock": True,
        }


def create_inference_engine(
    config: ModelConfig, force_mock: bool = False
) -> BaseInferenceEngine:
    """
    Factory function: returns HailoInferenceEngine if Hailo runtime & hardware present,
    or MockInferenceEngine if in mock mode / hardware absent.
    """
    rt_ok, _ = check_hailo_runtime_installed()
    dev_ok = check_hailo_device_node()

    if not force_mock and rt_ok and dev_ok:
        logger.info("Hailo-8L accelerator and runtime detected; using HailoInferenceEngine")
        return HailoInferenceEngine(config)
    else:
        if not force_mock:
            logger.info(
                "Hailo hardware or runtime not present (runtime=%s, device=%s); using MockInferenceEngine",
                rt_ok,
                dev_ok,
            )
        return MockInferenceEngine(config)
