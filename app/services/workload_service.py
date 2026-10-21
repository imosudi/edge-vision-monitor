"""
Thermal Stress Generator and Workload Service for Hailo-8L profiling (Phase 3).
Orchestrates Workload Suite (A, B, C, D) execution, thermal safety monitoring,
throttling governor response validation, and synchronised trajectory recording.
"""

from __future__ import annotations

import collections
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging_config import get_logger
from app.sources.manager import VideoSourceManager
from app.telemetry.trajectory import (
    TrajectoryEngine,
    TrajectoryPoint,
    TrajectorySession,
    get_trajectory_engine,
)

logger = get_logger("SERVICE.WORKLOAD")

# Hard physical silicon safety boundary (degrees Celsius)
HARD_SAFETY_LIMIT_C = 102.0

# Hysteresis recovery temperature boundary for throttling de-escalation
THROTTLING_RECOVERY_TEMP_C = 99.0


class WorkloadService:
    """
    Coordinates thermal stress generation, high-throughput saturation,
    safety boundary supervision, and trajectory session recording.
    """

    def __init__(
        self,
        source_manager: Optional[VideoSourceManager] = None,
        inference_service: Optional[Any] = None,
        telemetry_service: Optional[Any] = None,
        event_service: Optional[Any] = None,
        trajectory_engine: Optional[TrajectoryEngine] = None,
    ):
        self._source_manager = source_manager
        self._inference_service = inference_service
        self._telemetry_service = telemetry_service
        self._event_service = event_service
        self._trajectory_engine = trajectory_engine or get_trajectory_engine()

        # Operational state
        self._state = "idle"  # idle, starting, running, stopping, completed, aborted
        self._workload_type: Optional[str] = None
        self._workload_name: Optional[str] = None
        self._duration_seconds = 60.0
        self._target_temp_c = 100.0
        self._safety_temp_limit_c = HARD_SAFETY_LIMIT_C
        self._simulate = False
        self._stream_count = 4
        self._buffer_size = 120
        self._media_file: Optional[str] = None

        # Tracking state
        self._start_monotonic = 0.0
        self._start_utc: Optional[str] = None
        self._end_utc: Optional[str] = None
        self._abort_reason: Optional[str] = None
        self._initial_source_config: Optional[Dict[str, Any]] = None
        self._active_session_id: Optional[str] = None
        self._last_summary: Optional[Dict[str, Any]] = None

        # Live telemetry metrics observed during workload
        self._peak_tj_c: Optional[float] = None
        self._current_tj_c: Optional[float] = None
        self._current_ts0_c: Optional[float] = None
        self._current_ts1_c: Optional[float] = None
        self._current_clock_mhz: Optional[float] = None
        self._initial_clock_mhz: Optional[float] = None
        self._min_clock_mhz: Optional[float] = None
        self._throttling_level: Optional[int] = None
        self._throttling_active = False
        self._throttling_observed = False
        self._hysteresis_recovered = False
        self._fps_samples: collections.deque[float] = collections.deque(maxlen=300)
        self._sample_count = 0

        # Background supervisor thread
        self._supervisor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()

    # -------------------------------------------------------------------------
    # Workload Normalisation
    # -------------------------------------------------------------------------

    @staticmethod
    def normalise_workload_type(raw_type: str) -> str:
        """Normalise workload identifier string to canonical 'A', 'B', 'C', or 'D'."""
        cleaned = raw_type.strip().upper()
        if cleaned.startswith("WORKLOAD_"):
            cleaned = cleaned[9:]
        if cleaned in ("A", "B", "C", "D"):
            return cleaned
        raise ValueError(
            f"Unsupported workload '{raw_type}'. Supported workloads are 'A', 'B', 'C', or 'D'."
        )

    @staticmethod
    def get_workload_title(workload_type: str) -> str:
        """Return human-readable descriptive title for workload category."""
        titles = {
            "A": "Workload A: High-Throughput Object Detection",
            "B": "Workload B: High NPU Utilisation and Sustained Thermal Load",
            "C": "Workload C: Near-Threshold Thermal Monitoring and Safety Abort",
            "D": "Workload D: Throttling-Response and Hysteresis Validation",
        }
        return titles.get(workload_type, f"Workload {workload_type}")

    # -------------------------------------------------------------------------
    # Lifecycle Control
    # -------------------------------------------------------------------------

    def start_workload(
        self,
        workload_type: str,
        duration_seconds: float = 60.0,
        target_temp_c: float = 100.0,
        safety_temp_limit_c: float = HARD_SAFETY_LIMIT_C,
        simulate: bool = False,
        stream_count: int = 4,
        buffer_size: int = 120,
        media_file: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Initiate a supervised thermal stress or throughput benchmarking run.
        """
        canonical_type = self.normalise_workload_type(workload_type)
        safe_duration = max(5.0, min(3600.0, float(duration_seconds)))
        safe_safety_limit = min(HARD_SAFETY_LIMIT_C, max(60.0, float(safety_temp_limit_c)))
        safe_target_temp = min(safe_safety_limit, max(50.0, float(target_temp_c)))

        with self._lock:
            if self._state in ("running", "starting"):
                raise RuntimeError(
                    f"A workload ({self._workload_name}) is already active. Stop it before initiating another."
                )

            self._state = "starting"
            self._workload_type = canonical_type
            self._workload_name = f"workload_{canonical_type.lower()}"
            self._duration_seconds = safe_duration
            self._target_temp_c = safe_target_temp
            self._safety_temp_limit_c = safe_safety_limit
            self._simulate = simulate
            self._stream_count = max(1, min(16, int(stream_count)))
            self._buffer_size = max(10, min(500, int(buffer_size)))
            self._media_file = media_file

            # Reset monitoring metrics
            self._start_monotonic = time.monotonic()
            self._start_utc = datetime.now(timezone.utc).isoformat()
            self._end_utc = None
            self._abort_reason = None
            self._peak_tj_c = None
            self._current_tj_c = None
            self._current_ts0_c = None
            self._current_ts1_c = None
            self._current_clock_mhz = None
            self._initial_clock_mhz = None
            self._min_clock_mhz = None
            self._throttling_level = None
            self._throttling_active = False
            self._throttling_observed = False
            self._hysteresis_recovered = False
            self._fps_samples.clear()
            self._sample_count = 0
            self._stop_event.clear()

            # Record initial video source configuration to enable seamless restoration
            self._preserve_active_source()

            # Configure high-throughput benchmark mode on InferenceService
            if self._inference_service is not None:
                try:
                    self._inference_service.set_benchmark_mode(True)
                except Exception as e:
                    logger.warning("Could not enable inference benchmark mode: %s", e)

            # Switch video ingress according to workload strategy
            self._activate_workload_ingress(canonical_type)

            # Start trajectory recording session
            session_metadata = {
                "workload_type": canonical_type,
                "workload_title": self.get_workload_title(canonical_type),
                "duration_seconds": safe_duration,
                "target_temp_c": safe_target_temp,
                "safety_temp_limit_c": safe_safety_limit,
                "simulate": simulate,
                "stream_count": self._stream_count if canonical_type in ("B", "C", "D") else 1,
            }
            session = self._trajectory_engine.start_session(
                workload_name=self._workload_name,
                metadata=session_metadata,
            )
            self._active_session_id = session.session_id

            # Emit lifecycle event
            if self._event_service is not None:
                try:
                    self._event_service.emit(
                        event_type="WORKLOAD_STARTED",
                        message=(
                            f"Initiated {self.get_workload_title(canonical_type)} "
                            f"(duration: {safe_duration}s, safety limit: {safe_safety_limit}°C)"
                        ),
                        severity="INFO",
                        component="WORKLOAD",
                    )
                except Exception as e:
                    logger.debug("Failed emitting workload start event: %s", e)

            self._state = "running"
            self._supervisor_thread = threading.Thread(
                target=self._supervision_loop,
                name="WorkloadSupervisorWorker",
                daemon=True,
            )
            self._supervisor_thread.start()

            logger.info(
                "Workload %s started: duration=%.1fs, safety_limit=%.1f°C, target=%.1f°C, session=%s",
                canonical_type,
                safe_duration,
                safe_safety_limit,
                safe_target_temp,
                self._active_session_id,
            )
            return self.get_status()

    def stop_workload(self, reason: Optional[str] = None) -> Dict[str, Any]:
        """
        Manually stop the active workload and restore nominal system operational configuration.
        """
        with self._lock:
            if self._state not in ("running", "starting"):
                return self.get_status()

            logger.info("Stopping workload %s (reason: %s)...", self._workload_name, reason or "user request")
            self._state = "stopping"
            self._abort_reason = reason
            self._stop_event.set()

        # Wait for supervisor thread to complete cleanup
        if self._supervisor_thread and self._supervisor_thread.is_alive():
            if threading.current_thread() != self._supervisor_thread:
                self._supervisor_thread.join(timeout=3.0)

        with self._lock:
            if self._state == "stopping":
                self._state = "completed" if not reason else "aborted"
            return self.get_status()

    # -------------------------------------------------------------------------
    # Ingress and Mode Setup
    # -------------------------------------------------------------------------

    def _preserve_active_source(self) -> None:
        """Capture currently active video source attributes for subsequent restoration."""
        if self._source_manager is None:
            return
        try:
            st = self._source_manager.get_status()
            self._initial_source_config = {
                "active_type": st.get("active_type", "file"),
                "source_id": st.get("source_id"),
                "file_path": st.get("file_path"),
            }
        except Exception as e:
            logger.debug("Failed saving initial source config: %s", e)
            self._initial_source_config = None

    def _activate_workload_ingress(self, canonical_type: str) -> None:
        """Engage specific high-throughput ingress feeder matching the selected workload."""
        if self._source_manager is None:
            return

        try:
            if canonical_type == "A":
                # Workload A: In-memory circular RAM buffer
                self._source_manager.start_ring_buffer_source(
                    file_path=self._media_file,
                    buffer_size=self._buffer_size,
                    unthrottled=True,
                )
            else:
                # Workload B, C, D: Multi-stream concurrent ingestion feeder
                file_paths = [self._media_file] if self._media_file else None
                self._source_manager.start_multi_stream_source(
                    stream_count=self._stream_count,
                    file_paths=file_paths,
                    buffer_size_per_stream=max(15, self._buffer_size // max(1, self._stream_count)),
                    unthrottled=True,
                )
        except Exception as e:
            logger.error("Failed activating workload ingress for %s: %s", canonical_type, e)

    def _restore_nominal_state(self) -> None:
        """Restore default inference mode and initial video source."""
        logger.info("Restoring nominal system operational configuration...")

        # 1. Restore preview encoding in InferenceService
        if self._inference_service is not None:
            try:
                self._inference_service.set_benchmark_mode(False)
            except Exception as e:
                logger.debug("Failed disabling benchmark mode on inference service: %s", e)

        # 2. Restore video source
        if self._source_manager is not None:
            try:
                prev = self._initial_source_config or {}
                prev_type = prev.get("active_type", "file")
                if prev_type in ("ring_buffer", "multi_stream", "none", ""):
                    prev_type = "file"

                prev_file = prev.get("file_path")
                self._source_manager.switch_source(prev_type, file_path=prev_file)
                logger.info("Restored video source to '%s' (%s)", prev_type, prev_file or "default")
            except Exception as e:
                logger.warning("Failed restoring video source: %s", e)

    # -------------------------------------------------------------------------
    # Supervision Loop
    # -------------------------------------------------------------------------

    def _supervision_loop(self) -> None:
        """
        Background safety watchdog, telemetry sampler, and duration governor.
        Runs at 10 Hz (0.1s interval) for responsive thermal threshold reaction.
        """
        check_interval = 0.1
        simulated_temp = 50.0

        try:
            while not self._stop_event.is_set():
                now_mono = time.monotonic()
                elapsed = now_mono - self._start_monotonic

                # 1. Check duration expiration
                if elapsed >= self._duration_seconds:
                    logger.info("Workload %s elapsed target duration (%.1fs)", self._workload_name, self._duration_seconds)
                    with self._lock:
                        self._state = "completed"
                    break

                # 2. Sample hardware thermals and inference metrics
                self._sample_telemetry_state(elapsed, simulated_temp)

                # 3. Handle simulation advancement if requested
                if self._simulate:
                    simulated_temp = self._advance_simulation(elapsed, simulated_temp)

                # 4. Critical Thermal Safety Guard
                if self._current_tj_c is not None:
                    # Hard safety limit check
                    if self._current_tj_c >= self._safety_temp_limit_c:
                        abort_msg = (
                            f"Safety abort triggered: Junction temperature reached {self._current_tj_c:.1f}°C "
                            f"(threshold: {self._safety_temp_limit_c:.1f}°C)"
                        )
                        logger.critical(abort_msg)
                        with self._lock:
                            self._state = "aborted"
                            self._abort_reason = abort_msg
                        if self._event_service is not None:
                            try:
                                self._event_service.emit(
                                    event_type="THERMAL_SAFETY_ABORT",
                                    message=abort_msg,
                                    severity="CRITICAL",
                                    component="SAFETY",
                                )
                            except Exception:
                                pass
                        break

                    # Workload C: Target temperature reached check
                    if self._workload_type == "C" and self._current_tj_c >= self._target_temp_c:
                        logger.info(
                            "Workload C reached target temperature threshold: %.1f°C >= %.1f°C",
                            self._current_tj_c,
                            self._target_temp_c,
                        )

                # 5. Sleep until next evaluation cycle
                time.sleep(check_interval)

        except Exception as exc:
            logger.exception("Unexpected error in workload supervisor loop: %s", exc)
            with self._lock:
                self._state = "aborted"
                self._abort_reason = f"Internal supervisor exception: {exc}"
        finally:
            self._finalise_workload_run()

    def _sample_telemetry_state(self, elapsed: float, sim_temp: float) -> None:
        """Sample and evaluate current silicon metrics and inference throughput."""
        ts0: Optional[float] = None
        ts1: Optional[float] = None
        tj: Optional[float] = None
        clock_mhz: Optional[float] = None
        throttling_lvl: Optional[int] = None
        throttling_act = False
        fps = 0.0

        # Retrieve real hardware metrics from TelemetryService or IPC
        metrics = self._get_latest_metrics()
        inf_stats = self._get_latest_inference_stats()

        if self._simulate:
            tj = round(sim_temp, 1)
            ts0 = round(sim_temp - 0.5, 1)
            ts1 = round(sim_temp + 0.5, 1)
            if tj >= 100.0:
                clock_mhz = 200.0
                throttling_lvl = 1
                throttling_act = True
            else:
                clock_mhz = 400.0
                throttling_lvl = 0
                throttling_act = False
            fps = 28.5 if not throttling_act else 14.2
        else:
            def _extract(key: str) -> Optional[float]:
                v = metrics.get(key)
                if isinstance(v, dict):
                    val = v.get("value")
                    return float(val) if val is not None else None
                try:
                    return float(v) if v is not None else None
                except (ValueError, TypeError):
                    return None

            ts0 = _extract("hailo_temp_ts0_c")
            ts1 = _extract("hailo_temp_ts1_c")
            tj = _extract("hailo_junction_temperature_c") or _extract("hailo_temperature_c")
            if tj is None and (ts0 is not None or ts1 is not None):
                tj = max(v for v in (ts0, ts1) if v is not None)

            clock_mhz = _extract("hailo_clock_frequency_mhz")
            lvl = _extract("hailo_throttling_level")
            throttling_lvl = int(lvl) if lvl is not None else None

            th_act_raw = _extract("hailo_throttling_active")
            if th_act_raw is not None:
                throttling_act = th_act_raw > 0.0
            else:
                throttling_act = (throttling_lvl is not None and throttling_lvl > 0) or (tj is not None and tj >= 104.0)

            fps = float(inf_stats.get("current_fps", 0.0))

        with self._lock:
            self._current_ts0_c = ts0
            self._current_ts1_c = ts1
            self._current_tj_c = tj
            self._current_clock_mhz = clock_mhz
            self._throttling_level = throttling_lvl
            self._throttling_active = throttling_act
            self._sample_count += 1

            if tj is not None:
                if self._peak_tj_c is None or tj > self._peak_tj_c:
                    self._peak_tj_c = tj

            if clock_mhz is not None:
                if self._initial_clock_mhz is None:
                    self._initial_clock_mhz = clock_mhz
                if self._min_clock_mhz is None or clock_mhz < self._min_clock_mhz:
                    self._min_clock_mhz = clock_mhz

            if throttling_act:
                self._throttling_observed = True

            # Track hysteresis recovery for Workload D:
            # Active throttling was observed, and now temperature has dropped back below 99.0°C
            # with clock stepping back up to nominal.
            if self._throttling_observed and not throttling_act:
                if tj is not None and tj < THROTTLING_RECOVERY_TEMP_C:
                    self._hysteresis_recovered = True

            if fps > 0:
                self._fps_samples.append(fps)

    def _advance_simulation(self, elapsed: float, current_sim_temp: float) -> float:
        """Simulate realistic thermal trajectory curve for software validation."""
        # Simulated thermal ramp: rises asymptotically toward an equilibrium
        # For Workload C / D, target near 101.5°C to test threshold detection
        if self._workload_type in ("C", "D"):
            target_equilibrium = 101.5
        elif self._workload_type == "B":
            target_equilibrium = 78.0
        else:
            target_equilibrium = 65.0

        rate = 0.08  # Thermal rise velocity constant
        delta = (target_equilibrium - current_sim_temp) * rate * 0.1
        return current_sim_temp + delta

    def _get_latest_metrics(self) -> Dict[str, Any]:
        """Fetch latest telemetry metrics dictionary from service or IPC."""
        if self._telemetry_service is not None:
            try:
                return self._telemetry_service.get_current_metrics()
            except Exception:
                pass
        try:
            from app.core.ipc import get_ipc_telemetry_metrics
            return get_ipc_telemetry_metrics()
        except Exception:
            return {}

    def _get_latest_inference_stats(self) -> Dict[str, Any]:
        """Fetch latest inference stats dictionary from service or IPC."""
        if self._inference_service is not None:
            try:
                return self._inference_service.get_stats()
            except Exception:
                pass
        try:
            from app.core.ipc import get_ipc_inference_stats
            return get_ipc_inference_stats()
        except Exception:
            return {}

    def _finalise_workload_run(self) -> None:
        """Close trajectory session, compile summary, and restore nominal system state."""
        with self._lock:
            self._end_utc = datetime.now(timezone.utc).isoformat()
            if self._state not in ("aborted", "completed"):
                self._state = "completed"

        # 1. Stop active trajectory session and record summary
        try:
            session = self._trajectory_engine.stop_session()
            if session is not None:
                self._last_summary = session.summary()
                # Augment summary with workload specific thermal metrics
                self._last_summary["workload_evaluation"] = {
                    "workload_type": self._workload_type,
                    "peak_tj_c": self._peak_tj_c,
                    "initial_clock_mhz": self._initial_clock_mhz,
                    "min_clock_mhz": self._min_clock_mhz,
                    "throttling_observed": self._throttling_observed,
                    "hysteresis_recovered": self._hysteresis_recovered,
                    "safety_abort_triggered": self._state == "aborted",
                    "abort_reason": self._abort_reason,
                }
        except Exception as e:
            logger.error("Failed closing trajectory session: %s", e)

        # 2. Restore nominal system ingress and preview rate
        self._restore_nominal_state()

        # 3. Publish completion event
        if self._event_service is not None:
            try:
                sev = "WARNING" if self._state == "aborted" else "INFO"
                self._event_service.emit(
                    event_type="WORKLOAD_COMPLETED" if self._state == "completed" else "WORKLOAD_ABORTED",
                    message=(
                        f"Workload {self._workload_type} finished with status '{self._state}'. "
                        f"Peak Tj: {self._peak_tj_c or 0:.1f}°C"
                    ),
                    severity=sev,
                    component="WORKLOAD",
                )
            except Exception as e:
                logger.debug("Failed emitting workload completion event: %s", e)

        logger.info(
            "Workload %s finalised (state: %s, peak_tj: %s°C, session: %s)",
            self._workload_name,
            self._state,
            f"{self._peak_tj_c:.1f}" if self._peak_tj_c is not None else "N/A",
            self._active_session_id,
        )

    # -------------------------------------------------------------------------
    # Status and Export
    # -------------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Return a structured real-time status dictionary of active or last workload."""
        with self._lock:
            elapsed = (time.monotonic() - self._start_monotonic) if self._state in ("running", "starting") else 0.0
            if self._duration_seconds > 0:
                prog = min(100.0, round((elapsed / self._duration_seconds) * 100.0, 1))
            else:
                prog = 0.0

            mean_fps = (
                round(sum(self._fps_samples) / len(self._fps_samples), 1)
                if self._fps_samples
                else 0.0
            )
            curr_fps = self._fps_samples[-1] if self._fps_samples else 0.0

            return {
                "active": self._state in ("running", "starting"),
                "state": self._state,
                "workload_type": self._workload_type,
                "workload_name": self._workload_name,
                "workload_title": self.get_workload_title(self._workload_type) if self._workload_type else None,
                "elapsed_seconds": round(elapsed, 1),
                "duration_seconds": self._duration_seconds,
                "progress_percent": prog,
                "target_temp_c": self._target_temp_c,
                "safety_temp_limit_c": self._safety_temp_limit_c,
                "current_tj_c": self._current_tj_c,
                "peak_tj_c": self._peak_tj_c,
                "ts0_c": self._current_ts0_c,
                "ts1_c": self._current_ts1_c,
                "clock_frequency_mhz": self._current_clock_mhz,
                "initial_clock_mhz": self._initial_clock_mhz,
                "min_clock_mhz": self._min_clock_mhz,
                "throttling_level": self._throttling_level,
                "throttling_active": self._throttling_active,
                "throttling_observed": self._throttling_observed,
                "hysteresis_recovered": self._hysteresis_recovered,
                "current_fps": curr_fps,
                "mean_fps": mean_fps,
                "samples_count": self._sample_count,
                "abort_reason": self._abort_reason,
                "session_id": self._active_session_id,
                "session_summary": self._last_summary,
            }

    def export_trajectory_csv(self, session_id: Optional[str] = None) -> str:
        """Export trajectory points for requested or active session as CSV."""
        target_id = session_id or self._active_session_id
        return self._trajectory_engine.export_csv(target_id)

    def export_trajectory_json(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Export trajectory points for requested or active session as JSON."""
        target_id = session_id or self._active_session_id
        return self._trajectory_engine.export_json(target_id)

    def get_session_history(self) -> List[Dict[str, Any]]:
        """Return summaries of all completed profiling sessions."""
        with self._trajectory_engine._lock:
            history = list(self._trajectory_engine._session_history)
        return [s.summary() for s in history]


# Singleton instance container
_workload_service_instance: Optional[WorkloadService] = None
_workload_service_lock = threading.Lock()


def get_workload_service() -> WorkloadService:
    """Retrieve or lazily initialise global singleton WorkloadService."""
    global _workload_service_instance
    if _workload_service_instance is None:
        with _workload_service_lock:
            if _workload_service_instance is None:
                from app.core.lifecycle import get_lifecycle_manager

                mgr = get_lifecycle_manager()
                _workload_service_instance = WorkloadService(
                    source_manager=mgr.source_manager,
                    inference_service=mgr.inference_service,
                    telemetry_service=mgr.telemetry_service,
                    event_service=mgr.event_service,
                )
    return _workload_service_instance


# Semantic Alias for Phase 3 commitment naming
ThermalStressGenerator = WorkloadService
