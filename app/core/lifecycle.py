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


_lifecycle_instance: Optional[ApplicationLifecycleManager] = None


def get_lifecycle_manager() -> ApplicationLifecycleManager:
    """Global singleton accessor for ApplicationLifecycleManager."""
    global _lifecycle_instance
    if _lifecycle_instance is None:
        _lifecycle_instance = ApplicationLifecycleManager()
    return _lifecycle_instance
