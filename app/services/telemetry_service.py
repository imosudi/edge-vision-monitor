"""
Telemetry background service managing periodic sampling, threshold checks,
and metrics distribution.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from app.core.config import TelemetryConfig
from app.core.ipc import publish_telemetry_snapshot
from app.core.logging_config import get_logger
from app.services.event_service import EventService
from app.storage.repository import TelemetryRepository
from app.telemetry.collector import TelemetryCollector

logger = get_logger("SERVICE.TELEMETRY")


class TelemetryService:
    """Runs periodic telemetry sampling loop in a background thread."""

    def __init__(
        self,
        config: TelemetryConfig,
        repository: Optional[TelemetryRepository] = None,
        event_service: Optional[EventService] = None,
    ):
        self._config = config
        self._repository = repository
        self._event_service = event_service
        self._collector = TelemetryCollector(config)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._sample_count = 0
        self._last_sample_time = 0.0
        self._active_alarms: Dict[str, str] = {}

    def start(self) -> None:
        """Start the background telemetry sampling thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._sampling_loop, name="TelemetryCollectorThread", daemon=True
        )
        self._thread.start()
        logger.info("Telemetry background service started (interval: %.1fs)", self._config.system_interval_seconds)

    def stop(self, timeout: float = 3.0) -> None:
        """Stop the sampling thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None
        self._collector.stop()
        logger.info("Telemetry background service stopped")

    def _sampling_loop(self) -> None:
        interval = self._config.system_interval_seconds

        while not self._stop_event.is_set():
            t_start = time.monotonic()
            try:
                samples = self._collector.sample_all()
                self._sample_count += 1
                self._last_sample_time = t_start

                # Persist asynchronously if repository is available
                if self._repository is not None:
                    self._repository.enqueue_telemetry(samples)

                # Check alarms / thresholds
                self._check_alarms(samples)

                # Publish latest snapshot to shared-memory IPC for decoupled gateway
                publish_telemetry_snapshot(
                    metrics=self._collector.get_latest_snapshot(),
                    catalog=self._collector.get_metric_catalog(),
                    alarms=self._active_alarms,
                    status=self.get_status(),
                )

                # Capture synchronised trajectory point into TrajectoryEngine
                try:
                    from app.telemetry.trajectory import get_trajectory_engine
                    inf_stats = {}
                    try:
                        from app.core.lifecycle import get_lifecycle_manager
                        mgr = get_lifecycle_manager()
                        if mgr and mgr.inference_service is not None:
                            inf_stats = mgr.inference_service.get_stats()
                    except Exception:
                        pass
                    get_trajectory_engine().capture_point(
                        metrics_snapshot=self._collector.get_latest_snapshot(),
                        inference_stats=inf_stats,
                        monotonic_ts=t_start,
                    )
                except Exception as traj_err:
                    logger.debug("Telemetry trajectory capture notice: %s", traj_err)

            except Exception as e:
                logger.error("Exception during telemetry sampling: %s", e, exc_info=True)

            elapsed = time.monotonic() - t_start
            sleep_time = max(0.05, interval - elapsed)
            time.sleep(sleep_time)

    def _check_alarms(self, samples) -> None:
        """Evaluate readings against user-configured warning/critical thresholds."""
        thresholds = self._config.thresholds
        for s in samples:
            if s.value is None or s.availability_status != "AVAILABLE":
                continue

            # CPU Temperature
            if "cpu" in s.metric_name and s.unit == "celsius":
                if s.value >= thresholds.critical_cpu_temp_c:
                    self._trigger_alarm(
                        s.metric_name,
                        f"CRITICAL: CPU temperature is {s.value}°C (threshold: {thresholds.critical_cpu_temp_c}°C)",
                        severity="CRITICAL",
                    )
                elif s.value >= thresholds.warning_cpu_temp_c:
                    self._trigger_alarm(
                        s.metric_name,
                        f"WARNING: CPU temperature is {s.value}°C (threshold: {thresholds.warning_cpu_temp_c}°C)",
                        severity="WARNING",
                    )
                else:
                    self._clear_alarm(s.metric_name)

            # Hailo NPU Temperature
            elif "hailo" in s.metric_name and s.unit == "celsius":
                if s.value >= thresholds.critical_hailo_temp_c:
                    self._trigger_alarm(
                        s.metric_name,
                        f"CRITICAL: Hailo NPU temperature is {s.value}°C (threshold: {thresholds.critical_hailo_temp_c}°C)",
                        severity="CRITICAL",
                    )
                elif s.value >= thresholds.warning_hailo_temp_c:
                    self._trigger_alarm(
                        s.metric_name,
                        f"WARNING: Hailo NPU temperature is {s.value}°C (threshold: {thresholds.warning_hailo_temp_c}°C)",
                        severity="WARNING",
                    )
                else:
                    self._clear_alarm(s.metric_name)

            # Raspberry Pi Throttling
            elif s.metric_name == "rpi_is_throttled" and s.value > 0:
                self._trigger_alarm(
                    "rpi_throttling",
                    "WARNING: Raspberry Pi hardware throttling or undervoltage detected!",
                    severity="WARNING",
                )
            elif s.metric_name == "rpi_is_throttled" and s.value == 0:
                self._clear_alarm("rpi_throttling")

            # CPU Thermal Throttling / Frequency Drop
            elif s.metric_name == "cpu_thermal_throttle_active" and s.value > 0:
                self._trigger_alarm(
                    "cpu_thermal_throttle",
                    "CRITICAL: CPU thermal throttling active! Processor clock has dropped below 2.4 GHz full base frequency.",
                    severity="CRITICAL",
                )
            elif s.metric_name == "cpu_thermal_throttle_active" and s.value == 0:
                self._clear_alarm("cpu_thermal_throttle")

            # ARM Frequency Capping
            elif s.metric_name == "rpi_arm_freq_capped_now" and s.value > 0:
                self._trigger_alarm(
                    "rpi_arm_freq_capped",
                    "WARNING: Raspberry Pi ARM frequency capping currently active!",
                    severity="WARNING",
                )
            elif s.metric_name == "rpi_arm_freq_capped_now" and s.value == 0:
                self._clear_alarm("rpi_arm_freq_capped")

            # Ambient Room Temperature (ESP32 / DHT22)
            elif s.metric_name == "ambient_temperature_c":
                if thresholds.critical_ambient_temp_c is not None and s.value >= thresholds.critical_ambient_temp_c:
                    self._trigger_alarm(
                        s.metric_name,
                        f"CRITICAL: Ambient room temperature is {s.value}°C (threshold: {thresholds.critical_ambient_temp_c}°C)",
                        severity="CRITICAL",
                    )
                elif thresholds.warning_ambient_temp_c is not None and s.value >= thresholds.warning_ambient_temp_c:
                    self._trigger_alarm(
                        s.metric_name,
                        f"WARNING: Ambient room temperature is {s.value}°C (threshold: {thresholds.warning_ambient_temp_c}°C)",
                        severity="WARNING",
                    )
                else:
                    self._clear_alarm(s.metric_name)

            # Ambient Relative Humidity (ESP32 / DHT22)
            elif s.metric_name == "ambient_humidity_percent":
                if thresholds.critical_ambient_humidity_percent is not None and s.value >= thresholds.critical_ambient_humidity_percent:
                    self._trigger_alarm(
                        s.metric_name,
                        f"CRITICAL: Ambient relative humidity is {s.value}% (threshold: {thresholds.critical_ambient_humidity_percent}%)",
                        severity="CRITICAL",
                    )
                elif thresholds.warning_ambient_humidity_percent is not None and s.value >= thresholds.warning_ambient_humidity_percent:
                    self._trigger_alarm(
                        s.metric_name,
                        f"WARNING: Ambient relative humidity is {s.value}% (threshold: {thresholds.warning_ambient_humidity_percent}%)",
                        severity="WARNING",
                    )
                else:
                    self._clear_alarm(s.metric_name)

        # Minimum Inference FPS Threshold Checks
        if thresholds.critical_min_fps is not None or thresholds.warning_min_fps is not None:
            try:
                from app.core.lifecycle import get_lifecycle_manager
                mgr = get_lifecycle_manager()
                if mgr.inference_service and mgr.inference_service.is_running():
                    cur_fps = mgr.inference_service.get_current_fps()
                    if mgr.inference_service._total_processed >= 15:
                        if thresholds.critical_min_fps is not None and cur_fps < thresholds.critical_min_fps:
                            self._trigger_alarm(
                                "inference_fps_min",
                                f"CRITICAL: Inference throughput is {cur_fps:.1f} FPS (below critical minimum: {thresholds.critical_min_fps:.1f} FPS)",
                                severity="CRITICAL",
                            )
                        elif thresholds.warning_min_fps is not None and cur_fps < thresholds.warning_min_fps:
                            self._trigger_alarm(
                                "inference_fps_min",
                                f"WARNING: Inference throughput is {cur_fps:.1f} FPS (below warning minimum: {thresholds.warning_min_fps:.1f} FPS)",
                                severity="WARNING",
                            )
                        else:
                            self._clear_alarm("inference_fps_min")
            except Exception as e:
                logger.debug("Could not evaluate minimum FPS alarm: %s", e)

    def _trigger_alarm(self, key: str, msg: str, severity: str = "WARNING") -> None:
        if self._active_alarms.get(key) != severity:
            self._active_alarms[key] = severity
            if self._event_service is not None:
                self._event_service.emit(
                    event_type="HARDWARE_ALARM",
                    message=msg,
                    severity=severity,
                    component="TELEMETRY",
                )

    def _clear_alarm(self, key: str) -> None:
        if key in self._active_alarms:
            del self._active_alarms[key]

    def get_current_metrics(self) -> Dict[str, Dict[str, Any]]:
        return self._collector.get_latest_snapshot()

    def get_catalog(self) -> List[Dict[str, Any]]:
        return self._collector.get_metric_catalog()

    def get_status(self) -> Dict[str, Any]:
        return {
            "active": self._thread is not None and self._thread.is_alive(),
            "sample_count": self._sample_count,
            "last_sample_monotonic": self._last_sample_time,
            "sampling_interval_seconds": self._config.system_interval_seconds,
            "active_alarms_count": len(self._active_alarms),
        }
