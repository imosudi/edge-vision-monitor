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

    def __init__(self, config: Optional[AppConfig] = None, service_mode: Optional[str] = None):
        self.config = config or load_config()
        self.service_mode: str = (service_mode or os.getenv("EVM_SERVICE", "all")).lower()
        self.repository: Optional[TelemetryRepository] = None
        self.event_service: Optional[EventService] = None
        self.telemetry_service: Optional[TelemetryService] = None
        self.inference_engine: Optional[BaseInferenceEngine] = None
        self.source_manager: Optional[VideoSourceManager] = None
        self.inference_service: Optional[InferenceService] = None
        self.workload_service: Optional[Any] = None
        self._is_started = False

    def startup(self, service_mode: Optional[str] = None) -> None:
        """Selective or sequential startup of application subsystems based on service role."""
        if self._is_started:
            return

        if service_mode:
            self.service_mode = service_mode.lower()

        setup_logging(self.config.server.log_level)
        mode = self.service_mode
        logger.info("Starting Edge Vision Monitor platform (role: %s)...", mode.upper())

        # 1. Storage Repository (Needed by storage, telemetry, gateway, and all)
        if mode in ("all", "storage", "telemetry", "gateway"):
            is_gateway = (mode == "gateway")
            self.repository = TelemetryRepository(
                db_path=self.config.storage.db_path,
                batch_size=self.config.storage.batch_size,
                flush_interval_seconds=self.config.storage.flush_interval_seconds,
                max_queue_size=self.config.storage.max_queue_size,
                retention_days=self.config.storage.retention_days,
                retention_hours=self.config.storage.retention_hours,
                prune_interval_seconds=self.config.storage.prune_interval_seconds,
                max_db_size_mb=self.config.storage.max_db_size_mb,
                read_only=is_gateway,
            )
            # Gateway has dedicated storage service handling writes
            if not is_gateway:
                self.repository.start()

        # 2. Event Service (Needed by event emitters and consumers)
        if mode in ("all", "storage", "telemetry", "gateway", "inference"):
            # Gateway is read-only; operational persistence is handled by storage service
            repo_for_events = None if mode == "gateway" else self.repository
            self.event_service = EventService(repo_for_events)

        # 3. Telemetry Service (Only for telemetry and all)
        if mode in ("all", "telemetry"):
            self.telemetry_service = TelemetryService(
                config=self.config.telemetry,
                repository=self.repository,
                event_service=self.event_service,
            )
            self.telemetry_service.start()

        # 4. Video Source Manager (Only for ingress and monolithic 'all')
        if mode in ("all", "ingress"):
            self.source_manager = VideoSourceManager(self.config.video)
            self.source_manager.start_default_source()

        # 5. Inference Engine & Inference Service (For inference and all)
        if mode in ("all", "inference"):
            self.inference_engine = create_inference_engine(self.config.model)
            res = self.inference_engine.initialize()
            if not res.is_valid and getattr(self.config.model, "active_backend", "hailo") == "hailo":
                logger.warning("Hailo initialisation failed: %s (%s). Falling back to CPU (ONNX Runtime)...", res.error_message, res.status)
                from app.inference.engine import ONNXInferenceEngine
                fallback_engine = ONNXInferenceEngine(self.config.model)
                fb_res = fallback_engine.initialize()
                if fb_res.is_valid:
                    self.inference_engine = fallback_engine
                    self.config.model.active_backend = "cpu"
                    logger.info("Successfully fell back to CPU (ONNX Runtime) engine")

            self.inference_service = InferenceService(
                engine=self.inference_engine,
                source_manager=self.source_manager if mode == "all" else None,
                repository=self.repository,
                event_service=self.event_service,
                server_config=self.config.server,
            )
            self.inference_service.start()
            try:
                from app.core.ipc import publish_backends_catalog, publish_engine_status
                publish_engine_status(self.inference_engine.get_status())
                publish_backends_catalog(self.get_available_backends())
            except Exception as e:
                logger.debug("Failed publishing initial engine/backends status: %s", e)

        # 6. Workload Service / Thermal Stress Generator
        try:
            from app.services.workload_service import WorkloadService
            self.workload_service = WorkloadService(
                source_manager=self.source_manager,
                inference_service=self.inference_service,
                telemetry_service=self.telemetry_service,
                event_service=self.event_service,
            )
        except Exception as e:
            logger.debug("Failed initialising WorkloadService: %s", e)

        if self.event_service:
            self.event_service.emit(
                event_type="SYSTEM_STARTUP",
                message=f"Edge Vision Monitor subsystem ({mode}) started successfully",
                severity="INFO",
                component="CORE",
            )
        self._is_started = True
        logger.info("Application lifecycle startup completed for role '%s'", mode)

    def shutdown(self) -> None:
        """Graceful sequential teardown of active application subsystems."""
        if not self._is_started:
            return

        logger.info("Shutting down Edge Vision Monitor platform (role: %s)...", self.service_mode)

        if self.event_service:
            self.event_service.emit(
                event_type="SYSTEM_SHUTDOWN",
                message=f"Subsystem ({self.service_mode}) shutdown initiated",
                severity="INFO",
                component="CORE",
            )

        # 0. Stop Workload Service first if active
        if self.workload_service:
            try:
                self.workload_service.stop_workload(reason="Subsystem shutdown")
            except Exception as e:
                logger.debug("Failed stopping active workload during shutdown: %s", e)

        # 1. Stop Inference Service
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
        logger.info("Application shutdown completed cleanly for role '%s'", self.service_mode)

    def switch_inference_backend(self, backend: str, model_path: Optional[str] = None) -> bool:
        """
        Switch inference backend at runtime (e.g. 'hailo' <-> 'cpu').
        """
        backend_lower = backend.lower()
        if self.inference_engine:
            st = self.inference_engine.get_status()
            current_backend = (st.get("backend") or "").lower()
            engine_ready = self.inference_engine.is_ready()
            if engine_ready and current_backend == backend_lower and (not model_path or model_path == getattr(self.inference_engine, "onnx_path", None) or model_path == getattr(self.config.model, "hef_path", None)):
                logger.info("Inference backend '%s' is already active and ready, skipping re-initialisation", backend)
                self.config.model.active_backend = backend_lower
                return True

        if backend_lower in ("cpu", "onnx"):
            if model_path:
                self.config.model.onnx_path = model_path
            from app.inference.engine import ONNXInferenceEngine
            new_engine = ONNXInferenceEngine(self.config.model, onnx_path=model_path)
        elif backend_lower == "hailo":
            if model_path:
                self.config.model.hef_path = model_path
            from app.inference.engine import HailoInferenceEngine
            new_engine = HailoInferenceEngine(self.config.model, hef_path=model_path)
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
        from app.inference.model_validation import check_hailo_device_node, check_hailo_runtime_installed, resolve_hef_path

        hailo_rt, _ = check_hailo_runtime_installed()
        hailo_dev = check_hailo_device_node()
        resolved_hef = resolve_hef_path(self.config.model.hef_path)
        hailo_hef_exists = os.path.isfile(resolved_hef) if resolved_hef else False

        onnx_candidates = [
            getattr(self.config.model, "onnx_path", None),
            "models/onnx/model.onnx",
            "models/model.onnx",
            "models/pytorch/best.onnx",
            "/app/models/onnx/model.onnx",
            "/app/models/model.onnx",
            "/app/models/pytorch/best.onnx",
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

        hailo_is_active = (current == "hailo" and getattr(self.inference_engine, "_is_ready", False))
        hailo_available = bool((hailo_rt and hailo_dev and hailo_hef_exists) or hailo_is_active)
        hailo_rt_installed = bool(hailo_rt or hailo_is_active)

        # In microservices gateway mode, hardware access is segregated into edge-vision-inference.
        # Check IPC engine status and HEF existence so gateway reports Hailo available to web UI
        if getattr(self, "service_mode", None) == "gateway" or self.inference_engine is None:
            from app.core.ipc import get_ipc_engine_status
            ipc_st = get_ipc_engine_status()
            if ipc_st:
                current = ipc_st.get("backend", "hailo" if "Hailo" in ipc_st.get("type", "") else "cpu")
                if ipc_st.get("hailo_ready") or (ipc_st.get("ready") and current == "hailo") or ipc_st.get("status") in ("READY", "NOMINAL", "STANDBY"):
                    hailo_available = True
                    hailo_rt_installed = True
            if hailo_hef_exists and (os.path.exists("/dev/hailo0") or getattr(self, "service_mode", None) == "gateway"):
                hailo_available = True
                hailo_rt_installed = True

        return {
            "current_backend": current,
            "backends": {
                "hailo": {
                    "name": "Hailo-8L NPU",
                    "available": hailo_available,
                    "model_path": resolved_hef or self.config.model.hef_path,
                    "device_node": "/dev/hailo0",
                    "runtime_installed": hailo_rt_installed,
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


def get_lifecycle_manager(config: Optional[AppConfig] = None, service_mode: Optional[str] = None) -> ApplicationLifecycleManager:
    """Global singleton accessor for ApplicationLifecycleManager."""
    global _lifecycle_instance
    if _lifecycle_instance is None:
        _lifecycle_instance = ApplicationLifecycleManager(config=config, service_mode=service_mode)
    return _lifecycle_instance


def run_service_worker(service_mode: str, config: Optional[AppConfig] = None) -> int:
    """
    Run a standalone microservice worker loop with signal handling.
    Used by ingress, inference, telemetry, and storage microservices.
    """
    import signal
    import threading
    import time

    manager = get_lifecycle_manager(config=config, service_mode=service_mode)
    manager.startup(service_mode=service_mode)

    shutdown_event = threading.Event()

    def handle_signal(sig, frame):
        logger.info("Service worker received signal %s, initiating graceful teardown...", sig)
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    logger.info("Microservice worker '%s' is running (PID: %s)", service_mode.upper(), os.getpid())
    if service_mode == "ingress" and manager.source_manager:
        try:
            from app.core.ipc import publish_source_status
            publish_source_status(manager.source_manager.get_status(), manager.source_manager.enumerate_sources())
        except Exception as e:
            logger.debug("Failed initial source status IPC publish: %s", e)
    elif service_mode == "inference" and manager.inference_engine:
        try:
            from app.core.ipc import publish_backends_catalog, publish_engine_status
            publish_engine_status(manager.inference_engine.get_status())
            publish_backends_catalog(manager.get_available_backends())
        except Exception as e:
            logger.debug("Failed initial inference IPC publish: %s", e)

    try:
        while not shutdown_event.is_set():
            if service_mode == "ingress" and manager.source_manager:
                try:
                    from app.core.ipc import consume_ipc_source_command, publish_source_status, publish_raw_frame
                    cmd = consume_ipc_source_command()
                    if cmd:
                        action = cmd.get("command")
                        kwargs = cmd.get("kwargs", {})
                        logger.info("Ingress worker received IPC command '%s': %s", action, kwargs)
                        if action == "switch_source":
                            stype = kwargs.get("source_type", "file")
                            call_kwargs = {k: v for k, v in kwargs.items() if k != "source_type"}
                            manager.source_manager.switch_source(stype, **call_kwargs)
                        elif action == "pause":
                            manager.source_manager.pause_playback()
                        elif action in ("play", "resume"):
                            manager.source_manager.resume_playback()
                        elif action == "restart":
                            manager.source_manager.restart_playback()
                        publish_source_status(manager.source_manager.get_status(), manager.source_manager.enumerate_sources())

                    # Capture and publish raw frame for decoupled inference worker
                    vframe = manager.source_manager.get_frame(timeout=0.03)
                    if vframe is not None and vframe.data is not None:
                        publish_raw_frame(
                            vframe.data.tobytes(),
                            vframe.width,
                            vframe.height,
                            3,
                            vframe.frame_seq,
                            vframe.source_id,
                        )

                        # Standby mode: publish unannotated live preview JPEG directly from source
                        now_ts = time.monotonic()
                        if (now_ts - getattr(manager, "_last_standby_jpeg_ts", 0.0)) >= 0.066:
                            manager._last_standby_jpeg_ts = now_ts
                            try:
                                from app.core.ipc import get_ipc_inference_stats
                                inf_st = get_ipc_inference_stats()
                                if not inf_st.get("is_running", False):
                                    import cv2
                                    from app.core.ipc import _atomic_write_bytes, PREVIEW_JPEG_FILE
                                    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), 75]
                                    ok, jpeg_bytes = cv2.imencode(".jpg", vframe.data, encode_params)
                                    if ok:
                                        _atomic_write_bytes(PREVIEW_JPEG_FILE, jpeg_bytes.tobytes())
                            except Exception:
                                pass
                    else:
                        time.sleep(0.005)
                except Exception as ipc_err:
                    logger.debug("Error in ingress worker loop: %s", ipc_err)
                    time.sleep(0.01)
            elif service_mode == "inference":
                try:
                    from app.core.ipc import consume_ipc_inference_command, publish_backends_catalog, publish_engine_status
                    cmd = consume_ipc_inference_command()
                    if cmd:
                        action = cmd.get("command")
                        kwargs = cmd.get("kwargs", {})
                        logger.info("Inference worker received IPC command '%s': %s", action, kwargs)
                        if action == "start":
                            reset_hist = kwargs.get("reset_history", True)
                            if reset_hist:
                                if manager.repository:
                                    manager.repository.reset_history()
                                if manager.inference_service:
                                    manager.inference_service.reset_stats()
                            if manager.inference_engine and not manager.inference_engine.is_ready():
                                logger.info("Inference engine is not ready on start command, re-initializing...")
                                manager.inference_engine.initialize()
                            if manager.inference_service:
                                manager.inference_service.start()
                        elif action == "stop":
                            if manager.inference_service:
                                manager.inference_service.stop()
                        elif action == "set_benchmark_mode":
                            enabled = kwargs.get("enabled", True)
                            if manager.inference_service:
                                manager.inference_service.set_benchmark_mode(enabled)
                                if enabled and not manager.inference_service.is_running():
                                    manager.inference_service.start()
                        elif action == "switch_backend":
                            backend = kwargs.get("backend", "hailo")
                            model_path = kwargs.get("model_path")
                            manager.switch_inference_backend(backend, model_path=model_path)
                        elif action == "reset_stats":
                            if manager.repository:
                                manager.repository.reset_history()
                            if manager.inference_service:
                                manager.inference_service.reset_stats()

                        if manager.inference_engine:
                            publish_engine_status(manager.inference_engine.get_status())
                        publish_backends_catalog(manager.get_available_backends())
                        if manager.inference_service:
                            from app.core.ipc import publish_inference_status
                            publish_inference_status(manager.inference_service.get_stats())
                except Exception as ipc_err:
                    logger.debug("Error in inference worker loop: %s", ipc_err)
                time.sleep(0.02)
            else:
                time.sleep(0.1)
    except KeyboardInterrupt:
        logger.info("Interrupted by user, terminating worker '%s'...", service_mode)
    finally:
        manager.shutdown()

    return 0
