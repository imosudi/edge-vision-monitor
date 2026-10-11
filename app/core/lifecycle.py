"""
Application Lifecycle Manager: centralized coordination of background services,
storage persistence, hardware interfaces, and graceful shutdown.
"""

from __future__ import annotations

import os
from typing import Optional

from app.core.config import AppConfig, load_config
from app.core.logging_config import get_logger, setup_logging
from app.inference.engine import BaseInferenceEngine, create_inference_engine
from app.services.event_service import EventService
from app.services.inference_service import InferenceService
from app.services.telemetry_service import TelemetryService
from app.sources.manager import VideoSourceManager
from app.storage.repository import TelemetryRepository

logger = get_logger("CORE.LIFECYCLE")


class ApplicationLifecycleManager:
    """Orchestrates initialisation, runtime coordination, and graceful teardown of all EVM subsystems."""

    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or load_config()
        self.repository: Optional[TelemetryRepository] = None
        self.event_service: Optional[EventService] = None
        self.telemetry_service: Optional[TelemetryService] = None
        self.inference_engine: Optional[BaseInferenceEngine] = None
        self.source_manager: Optional[VideoSourceManager] = None
        self.inference_service: Optional[InferenceService] = None
        self._is_started = False

    def startup(self) -> None:
        """Sequential startup of all application subsystems."""
        if self._is_started:
            return

        setup_logging(self.config.server.log_level)
        logger.info("Starting Edge Vision Monitor platform...")

        # 1. Storage Repository
        self.repository = TelemetryRepository(
            db_path=self.config.storage.db_path,
            batch_size=self.config.storage.batch_size,
            flush_interval_seconds=self.config.storage.flush_interval_seconds,
        )
        self.repository.start()

        # 2. Event Service
        self.event_service = EventService(self.repository)

        # 3. Telemetry Service
        self.telemetry_service = TelemetryService(
            config=self.config.telemetry,
            repository=self.repository,
            event_service=self.event_service,
        )
        self.telemetry_service.start()

        # 4. Video Source Manager
        self.source_manager = VideoSourceManager(self.config.video)
        self.source_manager.start_default_source()

        # 5. Inference Engine
        self.inference_engine = create_inference_engine(self.config.model)
        self.inference_engine.initialize()

        # 6. Inference Service
        self.inference_service = InferenceService(
            engine=self.inference_engine,
            source_manager=self.source_manager,
            repository=self.repository,
            event_service=self.event_service,
            server_config=self.config.server,
        )
        self.inference_service.start()

        self.event_service.emit(
            event_type="SYSTEM_STARTUP",
            message="Edge Vision Monitor platform started successfully",
            severity="INFO",
            component="CORE",
        )
        self._is_started = True
        logger.info("Application lifecycle startup completed")

    def shutdown(self) -> None:
        """Graceful sequential teardown of all application subsystems."""
        if not self._is_started:
            return

        logger.info("Shutting down Edge Vision Monitor platform...")

        if self.event_service:
            self.event_service.emit(
                event_type="SYSTEM_SHUTDOWN",
                message="Application shutdown initiated",
                severity="INFO",
                component="CORE",
            )

        # 1. Stop Inference Service first
        if self.inference_service:
            self.inference_service.stop(timeout=2.0)

        # 2. Stop Video Capture & release camera handles
        if self.source_manager:
            self.source_manager.stop()

        # 3. Stop Telemetry sampling
        if self.telemetry_service:
            self.telemetry_service.stop(timeout=2.0)

        # 4. Release Hailo accelerator
        if self.inference_engine:
            self.inference_engine.close()

        # 5. Flush and stop Storage Repository
        if self.repository:
            self.repository.stop(timeout=3.0)

        self._is_started = False
        logger.info("Application shutdown completed cleanly")

    def switch_inference_backend(self, backend: str, model_path: Optional[str] = None) -> bool:
        """
        Switch inference backend at runtime (e.g. 'hailo' <-> 'cpu').
        """
        backend_lower = backend.lower()
        if backend_lower in ("cpu", "onnx"):
            from app.inference.engine import ONNXInferenceEngine
            new_engine = ONNXInferenceEngine(self.config.model, onnx_path=model_path)
        elif backend_lower == "hailo":
            from app.inference.engine import HailoInferenceEngine
            new_engine = HailoInferenceEngine(self.config.model)
        elif backend_lower == "mock":
            from app.inference.engine import MockInferenceEngine
            new_engine = MockInferenceEngine(self.config.model)
        else:
            logger.error("Unknown inference backend requested: '%s'", backend)
            return False

        if not self.inference_service:
            logger.error("Inference service is not running")
            return False

        ok = self.inference_service.switch_engine(new_engine)
        if ok:
            self.inference_engine = new_engine
            self.config.model.active_backend = backend_lower
        return ok

    def get_available_backends(self) -> dict:
        """Check hardware and model file availability for Hailo and CPU backends."""
        from app.inference.model_validation import check_hailo_device_node, check_hailo_runtime_installed

        hailo_rt, _ = check_hailo_runtime_installed()
        hailo_dev = check_hailo_device_node()
        hailo_hef_exists = os.path.isfile(self.config.model.hef_path) if self.config.model.hef_path else False

        onnx_candidates = [
            getattr(self.config.model, "onnx_path", None),
            "models/onnx/model.onnx",
            "models/model.onnx",
            "models/pytorch/best.onnx",
        ]
        active_onnx = next((p for p in onnx_candidates if p and os.path.isfile(p)), None)

        try:
            import onnxruntime  # noqa: F401
            onnx_rt = True
        except ImportError:
            onnx_rt = False

        current = "mock"
        if self.inference_engine:
            st = self.inference_engine.get_status()
            current = st.get("backend", "hailo" if "Hailo" in st.get("type", "") else "cpu" if "CPU" in st.get("type", "") else "mock")

        return {
            "current_backend": current,
            "backends": {
                "hailo": {
                    "name": "Hailo-8L NPU",
                    "available": bool(hailo_rt and hailo_dev and hailo_hef_exists),
                    "model_path": self.config.model.hef_path,
                    "device_node": "/dev/hailo0",
                    "runtime_installed": bool(hailo_rt),
                },
                "cpu": {
                    "name": "CPU (ONNX Runtime)",
                    "available": bool(onnx_rt and active_onnx is not None),
                    "model_path": active_onnx,
                    "runtime_installed": bool(onnx_rt),
                },
            },
        }


_lifecycle_instance: Optional[ApplicationLifecycleManager] = None


def get_lifecycle_manager() -> ApplicationLifecycleManager:
    """Global singleton accessor for ApplicationLifecycleManager."""
    global _lifecycle_instance
    if _lifecycle_instance is None:
        _lifecycle_instance = ApplicationLifecycleManager()
    return _lifecycle_instance
