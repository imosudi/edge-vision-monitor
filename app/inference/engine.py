"""
Inference engine interface, HailoRT hardware accelerator execution,
and mock test engine.
"""

from __future__ import annotations

import collections
import glob
import math
import os
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
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
    def infer(
        self,
        frame: np.ndarray,
        frame_seq: int,
        source_id: str,
        skip_postprocessing: bool = False,
        preprocessed_tensor: Optional[np.ndarray] = None,
        scale: Optional[float] = None,
        pads: Optional[Tuple[int, int]] = None,
        wait_flush: bool = False,
    ) -> Optional[DetectionResult]:
        """Run preprocessing, model execution, and post-processing on a video frame."""
        pass

    def flush(self) -> List[DetectionResult]:
        """Flush and return any inflight asynchronous inference pipeline jobs."""
        return []

    @property
    def input_width(self) -> int:
        return 640

    @property
    def input_height(self) -> int:
        return 640

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

    def __init__(self, config: ModelConfig, hef_path: Optional[str] = None, pipeline_depth: int = 2):
        self._config = config
        from app.inference.model_validation import resolve_hef_path
        if hef_path:
            self._config.hef_path = hef_path
        else:
            resolved = resolve_hef_path(self._config.hef_path)
            if resolved and os.path.isfile(resolved):
                self._config.hef_path = resolved
        self._validation: Optional[ModelValidationResult] = None
        self._vdevice: Any = None
        self._infer_model: Any = None
        self._configured_infer_model: Any = None
        self._bindings_pool: List[Any] = []
        self._binding_idx: int = 0
        self._inflight_queue: collections.deque = collections.deque()
        self._pipeline_depth: int = max(1, min(4, pipeline_depth))
        self._use_infer_model: bool = False
        self._use_vstreams: bool = False
        self._labels: List[str] = []
        self._is_ready: bool = False

    @property
    def input_width(self) -> int:
        return (
            self._validation.input_width
            if (self._validation and self._validation.input_width)
            else (self._config.input_width or 640)
        )

    @property
    def input_height(self) -> int:
        return (
            self._validation.input_height
            if (self._validation and self._validation.input_height)
            else (self._config.input_height or 640)
        )

    def initialize(self) -> ModelValidationResult:
        from app.inference.model_validation import resolve_hef_path
        resolved = resolve_hef_path(self._config.hef_path)
        if resolved and os.path.isfile(resolved):
            self._config.hef_path = resolved

        self._validation = validate_model_artifacts(
            hef_path=self._config.hef_path,
            labels_path=self._config.labels_path,
            metadata_path=self._config.metadata_path,
            cfg_width=self._config.input_width,
            cfg_height=self._config.input_height,
        )
        self._labels = self._validation.labels
        if self._validation.hef_path and os.path.isfile(self._validation.hef_path):
            self._config.hef_path = self._validation.hef_path

        if not self._validation.is_valid:
            logger.warning(
                "Hailo inference engine cannot start: %s (%s)",
                self._validation.error_message,
                self._validation.status,
            )
            self._is_ready = False
            return self._validation

        try:
            import hailo_platform  # type: ignore

            configured = False

            # Path 1: Standard and proven InferVStreams API (optimized for Raspberry Pi 5 AI HAT+)
            if hasattr(hailo_platform, "InferVStreams") and hasattr(hailo_platform, "HEF"):
                try:
                    self._hef = hailo_platform.HEF(self._config.hef_path)
                    self._vdevice = hailo_platform.VDevice()
                    cfg = hailo_platform.ConfigureParams.create_from_hef(
                        self._hef, interface=hailo_platform.HailoStreamInterface.PCIe
                    )
                    net_groups = self._vdevice.configure(self._hef, cfg)
                    self._net_group = net_groups[0]
                    in_params = hailo_platform.InputVStreamParams.make(
                        self._net_group, quantized=False, format_type=hailo_platform.FormatType.UINT8
                    )
                    out_params = hailo_platform.OutputVStreamParams.make(
                        self._net_group, quantized=False, format_type=hailo_platform.FormatType.FLOAT32
                    )
                    self._input_name = list(in_params.keys())[0]
                    self._activated_network = self._net_group.activate()
                    self._activated_network.__enter__()
                    self._infer_pipeline = hailo_platform.InferVStreams(
                        self._net_group, in_params, out_params
                    )
                    self._infer_pipeline.__enter__()
                    self._use_vstreams = True
                    self._use_infer_model = False
                    configured = True
                    logger.info("Hailo-8L inference engine initialised successfully with InferVStreams: %s", self._config.hef_path)
                except Exception as vs_err:
                    logger.warning("InferVStreams initialisation failed: %s; trying InferModel fallback...", vs_err)
                    if hasattr(self, "_infer_pipeline") and self._infer_pipeline:
                        try:
                            self._infer_pipeline.__exit__(None, None, None)
                        except Exception:
                            pass
                        self._infer_pipeline = None
                    if hasattr(self, "_activated_network") and self._activated_network:
                        try:
                            self._activated_network.__exit__(None, None, None)
                        except Exception:
                            pass
                        self._activated_network = None
                    if self._vdevice:
                        try:
                            if hasattr(self._vdevice, "__exit__"):
                                self._vdevice.__exit__(None, None, None)
                            elif hasattr(self._vdevice, "release"):
                                self._vdevice.release()
                        except Exception:
                            pass
                        self._vdevice = None

            # Path 2: Modern InferModel API fallback
            if not configured and hasattr(hailo_platform, "InferModel"):
                self._vdevice = hailo_platform.VDevice()
                self._infer_model = self._vdevice.create_infer_model(self._config.hef_path)
                if hasattr(self._infer_model, "input"):
                    try:
                        self._infer_model.input().set_format_type(hailo_platform.FormatType.UINT8)
                    except Exception:
                        pass
                if hasattr(self._infer_model, "outputs"):
                    try:
                        for out in self._infer_model.outputs:
                            out.set_format_type(hailo_platform.FormatType.FLOAT32)
                    except Exception:
                        pass
                self._configured_infer_model = self._infer_model.configure()
                self._bindings_pool = [
                    self._configured_infer_model.create_bindings()
                    for _ in range(self._pipeline_depth)
                ]
                self._binding_idx = 0
                self._inflight_queue.clear()
                self._use_infer_model = True
                self._use_vstreams = False
                configured = True
                logger.info("Hailo-8L inference engine initialised successfully with InferModel: %s", self._config.hef_path)

            if not configured:
                raise RuntimeError("hailo_platform does not provide working InferVStreams or InferModel")

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

    def _drain_job_ctx(self, ctx: Dict[str, Any]) -> DetectionResult:
        ctx["job"].wait(timeout_ms=1000)
        hailo_ms = (time.monotonic() - ctx["t_hailo_start"]) * 1000.0
        raw_outputs = {}
        for out_name in self._infer_model.output_names:
            raw_outputs[out_name] = ctx["binding"].output(out_name).get_buffer()

        if ctx["skip_postprocessing"]:
            detections = []
            post_ms = 0.0
        else:
            detections, post_ms = decode_yolo11_detections(
                raw_outputs=raw_outputs,
                orig_w=ctx["orig_w"],
                orig_h=ctx["orig_h"],
                scale=ctx["scale"],
                pad_offsets=ctx["pads"],
                labels=self._labels,
                confidence_threshold=self._config.confidence_threshold,
                nms_iou_threshold=self._config.nms_iou_threshold,
                max_detections=self._config.max_detections,
            )

        total_latency_ms = (time.monotonic() - ctx["t_start"]) * 1000.0
        return DetectionResult(
            frame_seq=ctx["frame_seq"],
            source_id=ctx["source_id"],
            monotonic_ts=time.monotonic(),
            detections=detections,
            image_width=ctx["orig_w"],
            image_height=ctx["orig_h"],
            preprocessing_ms=ctx["prep_ms"],
            hailo_exec_ms=hailo_ms,
            postprocessing_ms=post_ms,
            total_latency_ms=total_latency_ms,
        )

    def flush(self) -> List[DetectionResult]:
        """Drain any inflight async inference jobs and return completed detection results."""
        results: List[DetectionResult] = []
        while self._inflight_queue:
            ctx = self._inflight_queue.popleft()
            try:
                res = self._drain_job_ctx(ctx)
                results.append(res)
            except Exception as e:
                logger.error("Error draining inflight Hailo inference job: %s", e)
        return results

    def infer(
        self,
        frame: np.ndarray,
        frame_seq: int,
        source_id: str,
        skip_postprocessing: bool = False,
        preprocessed_tensor: Optional[np.ndarray] = None,
        scale: Optional[float] = None,
        pads: Optional[Tuple[int, int]] = None,
        wait_flush: bool = False,
    ) -> Optional[DetectionResult]:
        if not self._is_ready:
            now_mono = time.monotonic()
            if (now_mono - getattr(self, "_last_init_retry_ts", 0.0)) >= 2.0:
                self._last_init_retry_ts = now_mono
                logger.info("Attempting automatic Hailo engine initialization during inference...")
                self.initialize()
            if not self._is_ready:
                return DetectionResult(
                    frame_seq=frame_seq,
                    source_id=source_id,
                    error_status="Engine not ready",
                )

        orig_h, orig_w = frame.shape[:2]
        t_start = time.monotonic()

        # 1. Preprocess or adopt cached tensor
        input_w = self.input_width
        input_h = self.input_height

        if preprocessed_tensor is not None:
            input_tensor = preprocessed_tensor
            prep_ms = 0.0
            if scale is None:
                scale = min(input_w / orig_w, input_h / orig_h)
            if pads is None:
                new_w = int(round(orig_w * scale))
                new_h = int(round(orig_h * scale))
                pads = ((input_w - new_w) // 2, (input_h - new_h) // 2)
        else:
            input_tensor, scale, pads, prep_ms = preprocess_frame(
                frame, input_height=input_h, input_width=input_w, to_rgb=True
            )

        # 2. Hailo Accelerator Execution
        t_hailo_start = time.monotonic()
        try:
            if getattr(self, "_use_infer_model", False):
                cur_binding = self._bindings_pool[self._binding_idx]
                self._binding_idx = (self._binding_idx + 1) % self._pipeline_depth

                input_names = self._infer_model.input_names
                try:
                    if input_names:
                        cur_binding.input(input_names[0]).set_buffer(input_tensor)
                    else:
                        cur_binding.input().set_buffer(input_tensor)
                except Exception:
                    # Adapt 3D / 4D shape if required
                    buf = np.squeeze(input_tensor, axis=0) if input_tensor.ndim == 4 else np.expand_dims(input_tensor, axis=0)
                    if input_names:
                        cur_binding.input(input_names[0]).set_buffer(buf)
                    else:
                        cur_binding.input().set_buffer(buf)

                self._configured_infer_model.wait_for_async_ready(timeout_ms=1000)
                job = self._configured_infer_model.run_async([cur_binding])

                frame_ctx = {
                    "job": job,
                    "binding": cur_binding,
                    "frame_seq": frame_seq,
                    "source_id": source_id,
                    "orig_w": orig_w,
                    "orig_h": orig_h,
                    "scale": scale,
                    "pads": pads,
                    "prep_ms": prep_ms,
                    "t_hailo_start": t_hailo_start,
                    "t_start": t_start,
                    "skip_postprocessing": skip_postprocessing,
                }
                self._inflight_queue.append(frame_ctx)

                if wait_flush or len(self._inflight_queue) >= self._pipeline_depth:
                    completed_ctx = self._inflight_queue.popleft()
                    return self._drain_job_ctx(completed_ctx)
                return None

            else:
                batch_tensor = input_tensor if input_tensor.ndim == 4 else np.expand_dims(input_tensor, axis=0)
                raw_outputs = self._infer_pipeline.infer({self._input_name: batch_tensor})
                hailo_ms = (time.monotonic() - t_hailo_start) * 1000.0

                if skip_postprocessing:
                    detections = []
                    post_ms = 0.0
                else:
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

    def close(self) -> None:
        self._is_ready = False
        try:
            self.flush()
        except Exception:
            pass
        try:
            if hasattr(self, "_infer_pipeline") and self._infer_pipeline:
                try:
                    self._infer_pipeline.__exit__(None, None, None)
                except Exception:
                    pass
                self._infer_pipeline = None
            if hasattr(self, "_activated_network") and self._activated_network:
                try:
                    self._activated_network.__exit__(None, None, None)
                except Exception:
                    pass
                self._activated_network = None
            if self._configured_infer_model:
                try:
                    if hasattr(self._configured_infer_model, "__exit__"):
                        self._configured_infer_model.__exit__(None, None, None)
                except Exception:
                    pass
                self._configured_infer_model = None
            if self._infer_model:
                self._infer_model = None
            if self._vdevice:
                try:
                    if hasattr(self._vdevice, "__exit__"):
                        self._vdevice.__exit__(None, None, None)
                    elif hasattr(self._vdevice, "release"):
                        self._vdevice.release()
                except Exception:
                    pass
                self._vdevice = None
            logger.info("Hailo inference engine resources released")
        except Exception as e:
            logger.warning("Error releasing Hailo resources: %s", e)

    def is_ready(self) -> bool:
        return self._is_ready

    def get_status(self) -> Dict[str, Any]:
        return {
            "type": "Hailo-8L",
            "backend": "hailo",
            "ready": self._is_ready,
            "hailo_ready": self._is_ready,
            "status": self._validation.status if self._validation else "UNINITIALIZED",
            "hef_path": self._config.hef_path,
            "error_message": self._validation.error_message if self._validation else None,
            "is_mock": False,
            "pipeline_depth": self._pipeline_depth if getattr(self, "_use_infer_model", False) else 1,
        }


class ONNXInferenceEngine(BaseInferenceEngine):
    """
    CPU inference engine using ONNX Runtime for YOLO11.
    Allows testing and running inference on the host CPU without NPU hardware.
    """

    def __init__(self, config: ModelConfig, onnx_path: Optional[str] = None):
        self._config = config
        self._onnx_path = onnx_path or getattr(config, "onnx_path", None) or "models/onnx/model.onnx"
        self._session: Any = None
        self._input_name: str = "images"
        self._labels: List[str] = []
        self._is_ready: bool = False
        self._validation: Optional[ModelValidationResult] = None
        self._input_width: int = config.input_width or 640
        self._input_height: int = config.input_height or 640

    def initialize(self) -> ModelValidationResult:
        import os
        self._labels = load_class_labels(self._config.labels_path)

        # Candidate paths to locate ONNX model
        search_paths = [
            self._onnx_path,
            "models/yolo11n.onnx",
            "models/onnx/model.onnx",
            "models/model.onnx",
            "models/pytorch/best.onnx",
            "/app/models/yolo11n.onnx",
            "/app/models/onnx/model.onnx",
            "/app/models/model.onnx",
            "/app/models/pytorch/best.onnx",
        ]
        found_path = None
        for p in search_paths:
            if p and os.path.isfile(p):
                found_path = p
                break
        if not found_path:
            import glob
            for pattern in ["models/**/*.onnx", "/app/models/**/*.onnx"]:
                matches = [m for m in glob.glob(pattern, recursive=True) if os.path.isfile(m)]
                if matches:
                    found_path = matches[0]
                    break

        if not found_path:
            self._is_ready = False
            self._validation = ModelValidationResult(
                is_valid=False,
                status="FILE_NOT_FOUND",
                hef_path=self._onnx_path,
                labels_count=len(self._labels),
                labels=self._labels,
                input_width=self._input_width,
                input_height=self._input_height,
                error_message=f"ONNX model file not found at '{self._onnx_path}'",
                hailo_runtime_available=False,
                device_available=False,
            )
            return self._validation

        self._onnx_path = found_path

        try:
            import onnxruntime as ort

            sess_options = ort.SessionOptions()
            sess_options.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 4)))
            sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

            self._session = ort.InferenceSession(
                self._onnx_path,
                sess_options=sess_options,
                providers=["CPUExecutionProvider"],
            )

            inputs = self._session.get_inputs()
            if inputs:
                self._input_name = inputs[0].name
                shape = inputs[0].shape
                if len(shape) == 4 and isinstance(shape[2], int) and isinstance(shape[3], int):
                    self._input_height = shape[2]
                    self._input_width = shape[3]

            self._is_ready = True
            logger.info("CPU (ONNX Runtime) inference engine initialised with model: %s", self._onnx_path)

            self._validation = ModelValidationResult(
                is_valid=True,
                status="READY",
                hef_path=self._onnx_path,
                labels_count=len(self._labels),
                labels=self._labels,
                input_width=self._input_width,
                input_height=self._input_height,
                hailo_runtime_available=False,
                device_available=False,
            )
            return self._validation

        except Exception as e:
            logger.error("Failed to load ONNX model: %s", e, exc_info=True)
            self._is_ready = False
            self._validation = ModelValidationResult(
                is_valid=False,
                status="CONFIG_ERROR",
                hef_path=self._onnx_path,
                labels_count=len(self._labels),
                labels=self._labels,
                error_message=str(e),
                hailo_runtime_available=False,
                device_available=False,
            )
            return self._validation

    @property
    def input_width(self) -> int:
        return self._input_width

    @property
    def input_height(self) -> int:
        return self._input_height

    def infer(
        self,
        frame: np.ndarray,
        frame_seq: int,
        source_id: str,
        skip_postprocessing: bool = False,
        preprocessed_tensor: Optional[np.ndarray] = None,
        scale: Optional[float] = None,
        pads: Optional[Tuple[int, int]] = None,
        wait_flush: bool = False,
    ) -> DetectionResult:
        if not self._is_ready or self._session is None:
            now_mono = time.monotonic()
            if (now_mono - getattr(self, "_last_init_retry_ts", 0.0)) >= 2.0:
                self._last_init_retry_ts = now_mono
                logger.info("Attempting automatic CPU ONNX engine initialization during inference...")
                self.initialize()
            if not self._is_ready or self._session is None:
                return DetectionResult(
                    frame_seq=frame_seq,
                    source_id=source_id,
                    error_status="CPU ONNX engine not ready",
                )

        orig_h, orig_w = frame.shape[:2]
        t_start = time.monotonic()

        # 1. Preprocess: letterbox + normalize float32 [0.0, 1.0] in NCHW format
        t_prep_start = time.monotonic()
        if preprocessed_tensor is not None:
            input_tensor = preprocessed_tensor
            prep_ms = 0.0
            if scale is None:
                scale = min(self._input_width / orig_w, self._input_height / orig_h)
            if pads is None:
                new_w = int(round(orig_w * scale))
                new_h = int(round(orig_h * scale))
                pads = ((self._input_width - new_w) // 2, (self._input_height - new_h) // 2)
        else:
            input_tensor, scale, pads, _ = preprocess_frame(
                frame, input_height=self._input_height, input_width=self._input_width, to_rgb=True
            )
            prep_ms = (time.monotonic() - t_prep_start) * 1000.0

        img_f32 = input_tensor.astype(np.float32) / 255.0
        if img_f32.ndim == 3:
            img_f32 = np.expand_dims(img_f32, axis=0)
        # input_tensor is [1, H, W, C]; permute to [1, C, H, W]
        nchw_tensor = np.transpose(img_f32, (0, 3, 1, 2))

        # 2. CPU ONNX Execution
        t_exec_start = time.monotonic()
        try:
            outputs = self._session.run(None, {self._input_name: nchw_tensor})
            raw_output = outputs[0]
            exec_ms = (time.monotonic() - t_exec_start) * 1000.0
        except Exception as e:
            exec_ms = (time.monotonic() - t_exec_start) * 1000.0
            logger.error("ONNX CPU inference execution error: %s", e)
            return DetectionResult(
                frame_seq=frame_seq,
                source_id=source_id,
                preprocessing_ms=prep_ms,
                hailo_exec_ms=exec_ms,
                total_latency_ms=(time.monotonic() - t_start) * 1000.0,
                error_status=str(e),
            )

        # 3. Post-process (skipped in benchmark mode)
        if skip_postprocessing:
            detections = []
            post_ms = 0.0
        else:
            detections, post_ms = decode_yolo11_detections(
                raw_outputs=raw_output,
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
            hailo_exec_ms=exec_ms,
            postprocessing_ms=post_ms,
            total_latency_ms=total_latency_ms,
        )

    def close(self) -> None:
        self._is_ready = False
        self._session = None
        logger.info("CPU ONNX inference engine released")

    def is_ready(self) -> bool:
        return self._is_ready

    def get_status(self) -> Dict[str, Any]:
        return {
            "type": "CPU (ONNX)",
            "backend": "cpu",
            "ready": self._is_ready,
            "status": self._validation.status if self._validation else "UNINITIALIZED",
            "model_path": self._onnx_path,
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

    @property
    def input_width(self) -> int:
        return self._config.input_width or 640

    @property
    def input_height(self) -> int:
        return self._config.input_height or 640

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

    def infer(
        self,
        frame: np.ndarray,
        frame_seq: int,
        source_id: str,
        skip_postprocessing: bool = False,
        preprocessed_tensor: Optional[np.ndarray] = None,
        scale: Optional[float] = None,
        pads: Optional[Tuple[int, int]] = None,
        wait_flush: bool = False,
    ) -> DetectionResult:
        orig_h, orig_w = frame.shape[:2]
        t_start = time.monotonic()

        if skip_postprocessing:
            detections = []
            post_ms = 0.0
        else:
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
            post_ms = 0.8

        prep_ms = 0.0 if preprocessed_tensor is not None else 1.2
        hailo_ms = 4.8
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
            "backend": "mock",
            "ready": self._is_ready,
            "status": "MOCK_ACTIVE",
            "hef_path": self._config.hef_path,
            "error_message": None,
            "is_mock": True,
        }


def create_inference_engine(
    config: ModelConfig,
    force_mock: bool = False,
    backend: Optional[str] = None,
) -> BaseInferenceEngine:
    """
    Factory function: returns requested backend engine:
      - 'cpu' -> ONNXInferenceEngine
      - 'hailo' -> HailoInferenceEngine (or fallback to CPU/Mock if Hailo absent)
      - 'mock' -> MockInferenceEngine
    """
    import os

    chosen = (backend or getattr(config, "active_backend", "hailo")).lower()

    if force_mock or chosen == "mock":
        return MockInferenceEngine(config)

    if chosen in ("cpu", "onnx"):
        logger.info("Instantiating CPU (ONNX Runtime) inference engine")
        return ONNXInferenceEngine(config)

    # Hailo requested
    rt_ok, _ = check_hailo_runtime_installed()
    dev_ok = check_hailo_device_node()

    if rt_ok and dev_ok:
        logger.info("Hailo-8L accelerator and runtime detected; using HailoInferenceEngine")
        return HailoInferenceEngine(config)
    else:
        # Check if ONNX model is available as CPU fallback
        onnx_file = getattr(config, "onnx_path", "models/onnx/model.onnx")
        if onnx_file and os.path.isfile(onnx_file):
            logger.info("Hailo not present; falling back to CPU (ONNX Runtime) engine (%s)", onnx_file)
            return ONNXInferenceEngine(config)

        if not force_mock:
            logger.info(
                "Hailo hardware or runtime not present (runtime=%s, device=%s); using MockInferenceEngine",
                rt_ok,
                dev_ok,
            )
        return MockInferenceEngine(config)
