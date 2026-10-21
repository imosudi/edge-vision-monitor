"""
Structured Trajectory Engine: time-series profiling, high-frequency telemetry sampling,
and CSV/JSON trajectory export for Hailo-8L throughput and thermal characterisation.
"""

from __future__ import annotations

import collections
import csv
import io
import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Generator, List, Optional, Tuple

from app.core.logging_config import get_logger

logger = get_logger("TELEMETRY.TRAJECTORY")


@dataclass
class TrajectoryPoint:
    """
    A single synchronized multi-channel observation combining accelerator thermals,
    silicon clock frequencies, throttling states, inference throughput, and host telemetry.
    """

    timestamp_utc: str
    monotonic_ts: float
    relative_seconds: float
    workload_name: str = "baseline"

    # Hailo-8L Thermals and Clock Frequency
    ts0_c: Optional[float] = None
    ts1_c: Optional[float] = None
    tj_c: Optional[float] = None
    clock_mhz: Optional[float] = None
    throttling_level: Optional[int] = None
    throttling_active: bool = False
    npu_util_percent: Optional[float] = None

    # Inference Throughput
    fps: float = 0.0

    # Host Telemetry
    cpu_load_percent: Optional[float] = None
    cpu_temp_c: Optional[float] = None
    fan_rpm: Optional[float] = None

    # Pipeline Latency Percentiles (p50, p95, p99 in milliseconds)
    lat_pre_p50_ms: float = 0.0
    lat_pre_p95_ms: float = 0.0
    lat_pre_p99_ms: float = 0.0

    lat_npu_p50_ms: float = 0.0
    lat_npu_p95_ms: float = 0.0
    lat_npu_p99_ms: float = 0.0

    lat_post_p50_ms: float = 0.0
    lat_post_p95_ms: float = 0.0
    lat_post_p99_ms: float = 0.0

    lat_total_p50_ms: float = 0.0
    lat_total_p95_ms: float = 0.0
    lat_total_p99_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert point to a JSON-serializable dictionary."""
        d = asdict(self)
        d["relative_seconds"] = round(self.relative_seconds, 3)
        return d

    def to_csv_row(self) -> Dict[str, Any]:
        """Convert point to a dictionary formatted for CSV writer."""
        return {
            "timestamp_utc": self.timestamp_utc,
            "relative_seconds": f"{self.relative_seconds:.3f}",
            "workload": self.workload_name,
            "hailo_ts0_c": f"{self.ts0_c:.1f}" if self.ts0_c is not None else "",
            "hailo_ts1_c": f"{self.ts1_c:.1f}" if self.ts1_c is not None else "",
            "hailo_tj_c": f"{self.tj_c:.1f}" if self.tj_c is not None else "",
            "hailo_clock_mhz": f"{self.clock_mhz:.1f}" if self.clock_mhz is not None else "",
            "hailo_throttling_level": str(self.throttling_level) if self.throttling_level is not None else "",
            "hailo_throttling_active": "1" if self.throttling_active else "0",
            "inference_fps": f"{self.fps:.1f}",
            "cpu_load_percent": f"{self.cpu_load_percent:.1f}" if self.cpu_load_percent is not None else "",
            "cpu_temp_c": f"{self.cpu_temp_c:.1f}" if self.cpu_temp_c is not None else "",
            "fan_rpm": f"{self.fan_rpm:.0f}" if self.fan_rpm is not None else "",
            "npu_util_percent": f"{self.npu_util_percent:.1f}" if self.npu_util_percent is not None else "",
            "lat_pre_p50_ms": f"{self.lat_pre_p50_ms:.2f}",
            "lat_pre_p95_ms": f"{self.lat_pre_p95_ms:.2f}",
            "lat_pre_p99_ms": f"{self.lat_pre_p99_ms:.2f}",
            "lat_npu_p50_ms": f"{self.lat_npu_p50_ms:.2f}",
            "lat_npu_p95_ms": f"{self.lat_npu_p95_ms:.2f}",
            "lat_npu_p99_ms": f"{self.lat_npu_p99_ms:.2f}",
            "lat_post_p50_ms": f"{self.lat_post_p50_ms:.2f}",
            "lat_post_p95_ms": f"{self.lat_post_p95_ms:.2f}",
            "lat_post_p99_ms": f"{self.lat_post_p99_ms:.2f}",
            "lat_total_p50_ms": f"{self.lat_total_p50_ms:.2f}",
            "lat_total_p95_ms": f"{self.lat_total_p95_ms:.2f}",
            "lat_total_p99_ms": f"{self.lat_total_p99_ms:.2f}",
        }


CSV_FIELDNAMES = [
    "timestamp_utc",
    "relative_seconds",
    "workload",
    "hailo_ts0_c",
    "hailo_ts1_c",
    "hailo_tj_c",
    "hailo_clock_mhz",
    "hailo_throttling_level",
    "hailo_throttling_active",
    "inference_fps",
    "cpu_load_percent",
    "cpu_temp_c",
    "fan_rpm",
    "npu_util_percent",
    "lat_pre_p50_ms",
    "lat_pre_p95_ms",
    "lat_pre_p99_ms",
    "lat_npu_p50_ms",
    "lat_npu_p95_ms",
    "lat_npu_p99_ms",
    "lat_post_p50_ms",
    "lat_post_p95_ms",
    "lat_post_p99_ms",
    "lat_total_p50_ms",
    "lat_total_p95_ms",
    "lat_total_p99_ms",
]


class TrajectorySession:
    """Encapsulates a bounded profiling or benchmarking session."""

    def __init__(
        self,
        session_id: str,
        workload_name: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.session_id = session_id
        self.workload_name = workload_name
        self.start_time_utc = datetime.now(timezone.utc).isoformat()
        self.end_time_utc: Optional[str] = None
        self.start_monotonic = time.monotonic()
        self.end_monotonic: Optional[float] = None
        self.metadata = metadata or {}
        self.points: List[TrajectoryPoint] = []
        self._lock = threading.Lock()

    def add_point(self, point: TrajectoryPoint) -> None:
        with self._lock:
            self.points.append(point)

    def close(self) -> None:
        if self.end_time_utc is None:
            self.end_time_utc = datetime.now(timezone.utc).isoformat()
            self.end_monotonic = time.monotonic()

    def summary(self) -> Dict[str, Any]:
        """Compute aggregate summary metrics over all collected trajectory points."""
        with self._lock:
            pts = list(self.points)

        duration = 0.0
        if pts:
            duration = pts[-1].relative_seconds - pts[0].relative_seconds
        elif self.end_monotonic:
            duration = self.end_monotonic - self.start_monotonic

        fps_vals = [p.fps for p in pts if p.fps > 0]
        tj_vals = [p.tj_c for p in pts if p.tj_c is not None]
        ts0_vals = [p.ts0_c for p in pts if p.ts0_c is not None]
        ts1_vals = [p.ts1_c for p in pts if p.ts1_c is not None]
        cpu_loads = [p.cpu_load_percent for p in pts if p.cpu_load_percent is not None]
        fan_rpms = [p.fan_rpm for p in pts if p.fan_rpm is not None]
        throttled_count = sum(1 for p in pts if p.throttling_active)

        return {
            "session_id": self.session_id,
            "workload_name": self.workload_name,
            "start_time_utc": self.start_time_utc,
            "end_time_utc": self.end_time_utc,
            "duration_seconds": round(duration, 2),
            "total_points": len(pts),
            "fps": {
                "mean": round(sum(fps_vals) / len(fps_vals), 1) if fps_vals else 0.0,
                "min": round(min(fps_vals), 1) if fps_vals else 0.0,
                "max": round(max(fps_vals), 1) if fps_vals else 0.0,
            },
            "thermals_c": {
                "tj_initial": round(tj_vals[0], 1) if tj_vals else None,
                "tj_peak": round(max(tj_vals), 1) if tj_vals else None,
                "tj_final": round(tj_vals[-1], 1) if tj_vals else None,
                "tj_mean": round(sum(tj_vals) / len(tj_vals), 1) if tj_vals else None,
                "ts0_peak": round(max(ts0_vals), 1) if ts0_vals else None,
                "ts1_peak": round(max(ts1_vals), 1) if ts1_vals else None,
            },
            "cpu_load_percent": {
                "mean": round(sum(cpu_loads) / len(cpu_loads), 1) if cpu_loads else None,
                "max": round(max(cpu_loads), 1) if cpu_loads else None,
            },
            "fan_rpm": {
                "mean": round(sum(fan_rpms) / len(fan_rpms), 0) if fan_rpms else None,
                "max": round(max(fan_rpms), 0) if fan_rpms else None,
            },
            "throttling": {
                "throttling_occurred": throttled_count > 0,
                "throttled_samples_count": throttled_count,
            },
            "metadata": self.metadata,
        }

    def export_csv(self) -> str:
        """Export session trajectory points as a CSV formatted string."""
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=CSV_FIELDNAMES,
            extrasaction="ignore",
            lineterminator="\r\n",
        )
        writer.writeheader()
        with self._lock:
            for pt in self.points:
                writer.writerow(pt.to_csv_row())
        return output.getvalue()

    def export_json(self) -> Dict[str, Any]:
        """Export session trajectory points as a structured dictionary."""
        with self._lock:
            pts_dict = [p.to_dict() for p in self.points]
        return {
            "session_id": self.session_id,
            "workload_name": self.workload_name,
            "start_time_utc": self.start_time_utc,
            "end_time_utc": self.end_time_utc,
            "summary": self.summary(),
            "points": pts_dict,
        }

    def save_csv(self, file_path: str) -> None:
        """Save session trajectory directly to a CSV file on disk."""
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(self.export_csv())
        logger.info("Saved trajectory CSV (%d points) to %s", len(self.points), p)

    def save_json(self, file_path: str) -> None:
        """Save session trajectory directly to a JSON file on disk."""
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.export_json(), f, indent=2)
        logger.info("Saved trajectory JSON (%d points) to %s", len(self.points), p)


class TrajectoryEngine:
    """
    Centralised Trajectory Engine managing in-memory circular buffers,
    profiling sessions, real-time snapshot conversions, and time-series exports.
    """

    def __init__(self, ring_buffer_capacity: int = 10000):
        self._capacity = max(100, ring_buffer_capacity)
        self._ring_buffer: Deque[TrajectoryPoint] = collections.deque(maxlen=self._capacity)
        self._lock = threading.Lock()
        self._active_session: Optional[TrajectorySession] = None
        self._session_history: List[TrajectorySession] = []
        self._base_monotonic = time.monotonic()

    # -------------------------------------------------------------------------
    # Session Management
    # -------------------------------------------------------------------------

    def start_session(
        self,
        workload_name: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TrajectorySession:
        """Start a dedicated trajectory profiling session."""
        with self._lock:
            if self._active_session is not None:
                self._active_session.close()
                self._session_history.append(self._active_session)

            session_id = f"traj_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            session = TrajectorySession(
                session_id=session_id,
                workload_name=workload_name,
                metadata=metadata,
            )
            self._active_session = session
            logger.info("Started trajectory profiling session: %s (workload: %s)", session_id, workload_name)
            return session

    def stop_session(self) -> Optional[TrajectorySession]:
        """Stop the currently active profiling session."""
        with self._lock:
            if self._active_session is None:
                return None
            session = self._active_session
            session.close()
            self._session_history.append(session)
            self._active_session = None
            logger.info(
                "Stopped trajectory profiling session: %s (%d points recorded)",
                session.session_id,
                len(session.points),
            )
            return session

    def is_recording(self) -> bool:
        """Return True if a named profiling session is currently active."""
        with self._lock:
            return self._active_session is not None

    def get_active_session(self) -> Optional[TrajectorySession]:
        """Return the currently active profiling session if any."""
        with self._lock:
            return self._active_session

    # -------------------------------------------------------------------------
    # Sampling and Ingestion
    # -------------------------------------------------------------------------

    def capture_point(
        self,
        metrics_snapshot: Dict[str, Any],
        inference_stats: Dict[str, Any],
        workload_name: Optional[str] = None,
        timestamp_utc: Optional[str] = None,
        monotonic_ts: Optional[float] = None,
    ) -> TrajectoryPoint:
        """
        Extract and normalise multi-channel telemetry readings and inference latency
        percentiles into a unified TrajectoryPoint, appending it to the ring buffer
        and active session.
        """
        now_mono = monotonic_ts if monotonic_ts is not None else time.monotonic()
        now_utc = timestamp_utc or datetime.now(timezone.utc).isoformat()

        with self._lock:
            active_sess = self._active_session

        active_workload = workload_name or (active_sess.workload_name if active_sess else "baseline")
        rel_sec = (now_mono - active_sess.start_monotonic) if active_sess else (now_mono - self._base_monotonic)

        # Helper to extract metric values safely
        def _get_val(key: str) -> Optional[float]:
            item = metrics_snapshot.get(key)
            if item is None:
                return None
            if isinstance(item, dict):
                v = item.get("value")
                return float(v) if v is not None else None
            try:
                return float(item)
            except (ValueError, TypeError):
                return None

        # Thermals and Hardware States
        ts0_c = _get_val("hailo_temp_ts0_c")
        ts1_c = _get_val("hailo_temp_ts1_c")
        tj_c = _get_val("hailo_junction_temperature_c") or _get_val("hailo_temperature_c")
        if tj_c is None and (ts0_c is not None or ts1_c is not None):
            tj_c = max(v for v in (ts0_c, ts1_c) if v is not None)

        clock_mhz = _get_val("hailo_clock_frequency_mhz")
        throttling_lvl_raw = _get_val("hailo_throttling_level")
        throttling_level = int(throttling_lvl_raw) if throttling_lvl_raw is not None else -1

        throttling_act_val = _get_val("hailo_throttling_active")
        if throttling_act_val is not None:
            throttling_active = throttling_act_val > 0.0
        else:
            throttling_active = (throttling_level >= 0) or (tj_c is not None and tj_c >= 104.0)

        npu_util = _get_val("hailo_utilization_percent")

        # Host Telemetry
        cpu_load = _get_val("cpu_utilisation_percent") or _get_val("cpu_util")
        cpu_temp = _get_val("cpu_temperature_c") or _get_val("hwmon_cpu_thermal_temp") or _get_val("cpu_temp")

        # Discover fan RPM across candidate sensor names
        fan_rpm = _get_val("hwmon_pwmfan_fan1_rpm")
        if fan_rpm is None:
            for k in metrics_snapshot.keys():
                if "fan" in k and "rpm" in k:
                    fan_rpm = _get_val(k)
                    if fan_rpm is not None:
                        break

        # Inference Throughput
        fps = float(inference_stats.get("current_fps", 0.0))

        # Latency Percentiles
        lat = inference_stats.get("latencies", {})
        pre = lat.get("preprocessing_ms", {})
        npu = lat.get("execution_ms", lat.get("hailo_execution_ms", {}))
        post = lat.get("postprocessing_ms", {})
        tot = lat.get("total_ms", {})

        def _p(sub_dict: Dict[str, Any], key: str, fallback_key: str = "median") -> float:
            v = sub_dict.get(key)
            if v is not None:
                return float(v)
            return float(sub_dict.get(fallback_key, 0.0))

        point = TrajectoryPoint(
            timestamp_utc=now_utc,
            monotonic_ts=now_mono,
            relative_seconds=rel_sec,
            workload_name=active_workload,
            ts0_c=ts0_c,
            ts1_c=ts1_c,
            tj_c=tj_c,
            clock_mhz=clock_mhz,
            throttling_level=throttling_level if throttling_level != -1 else None,
            throttling_active=throttling_active,
            npu_util_percent=npu_util,
            fps=fps,
            cpu_load_percent=cpu_load,
            cpu_temp_c=cpu_temp,
            fan_rpm=fan_rpm,
            lat_pre_p50_ms=_p(pre, "p50", "median"),
            lat_pre_p95_ms=_p(pre, "p95"),
            lat_pre_p99_ms=_p(pre, "p99"),
            lat_npu_p50_ms=_p(npu, "p50", "median"),
            lat_npu_p95_ms=_p(npu, "p95"),
            lat_npu_p99_ms=_p(npu, "p99"),
            lat_post_p50_ms=_p(post, "p50", "median"),
            lat_post_p95_ms=_p(post, "p95"),
            lat_post_p99_ms=_p(post, "p99"),
            lat_total_p50_ms=_p(tot, "p50", "median"),
            lat_total_p95_ms=_p(tot, "p95"),
            lat_total_p99_ms=_p(tot, "p99"),
        )

        with self._lock:
            self._ring_buffer.append(point)
            if self._active_session is not None:
                self._active_session.add_point(point)

        return point

    # -------------------------------------------------------------------------
    # Queries and Exports
    # -------------------------------------------------------------------------

    def get_recent_points(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return the most recent trajectory points from the circular buffer."""
        with self._lock:
            buf = list(self._ring_buffer)
        pts = buf[-limit:] if limit > 0 else buf
        return [p.to_dict() for p in pts]

    def export_csv(self, session_id: Optional[str] = None) -> str:
        """
        Export trajectory points as a CSV string. If session_id is provided,
        exports that specific session; otherwise exports active session or ring buffer.
        """
        target_session = self._resolve_session(session_id)
        if target_session is not None:
            return target_session.export_csv()

        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=CSV_FIELDNAMES,
            extrasaction="ignore",
            lineterminator="\r\n",
        )
        writer.writeheader()
        with self._lock:
            pts = list(self._ring_buffer)
        for pt in pts:
            writer.writerow(pt.to_csv_row())
        return output.getvalue()

    def export_json(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Export trajectory points as a structured JSON-serializable dictionary.
        """
        target_session = self._resolve_session(session_id)
        if target_session is not None:
            return target_session.export_json()

        with self._lock:
            pts = list(self._ring_buffer)
        pts_dict = [p.to_dict() for p in pts]
        return {
            "session_id": "ring_buffer",
            "workload_name": "continuous",
            "start_time_utc": pts[0].timestamp_utc if pts else None,
            "end_time_utc": pts[-1].timestamp_utc if pts else None,
            "total_points": len(pts),
            "points": pts_dict,
        }

    def stream_csv(self, session_id: Optional[str] = None) -> Generator[str, None, None]:
        """Stream trajectory points line by line as CSV chunks."""
        target_session = self._resolve_session(session_id)
        pts: List[TrajectoryPoint] = []
        if target_session is not None:
            with target_session._lock:
                pts = list(target_session.points)
        else:
            with self._lock:
                pts = list(self._ring_buffer)

        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=CSV_FIELDNAMES,
            extrasaction="ignore",
            lineterminator="\r\n",
        )
        writer.writeheader()
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        chunk_count = 0
        for pt in pts:
            writer.writerow(pt.to_csv_row())
            chunk_count += 1
            if chunk_count >= 500:
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)
                chunk_count = 0

        if output.tell() > 0:
            yield output.getvalue()

    def _resolve_session(self, session_id: Optional[str]) -> Optional[TrajectorySession]:
        with self._lock:
            if session_id:
                if self._active_session and self._active_session.session_id == session_id:
                    return self._active_session
                for s in self._session_history:
                    if s.session_id == session_id:
                        return s
                return None
            return self._active_session

    # -------------------------------------------------------------------------
    # Reconstruct from TelemetryRepository (Historical SQLite Queries)
    # -------------------------------------------------------------------------

    def reconstruct_from_repository(
        self,
        repository: Any,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        workload_name: str = "historical",
        limit: int = 50000,
    ) -> TrajectorySession:
        """
        Reconstruct a TrajectorySession from historical records stored in SQLite
        via TelemetryRepository.
        """
        session_id = f"recon_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        session = TrajectorySession(
            session_id=session_id,
            workload_name=workload_name,
            metadata={"start_time": start_time, "end_time": end_time, "source": "sqlite"},
        )

        from app.storage.database import get_connection

        conn = get_connection(repository._db_path)
        try:
            # Query telemetry samples
            t_query = "SELECT timestamp_utc, metric_name, value FROM telemetry_samples WHERE 1=1"
            t_params: List[Any] = []
            if start_time:
                t_query += " AND timestamp_utc >= ?"
                t_params.append(start_time)
            if end_time:
                t_query += " AND timestamp_utc <= ?"
                t_params.append(end_time)
            t_query += " ORDER BY timestamp_utc ASC, id ASC LIMIT ?"
            t_params.append(limit)
            t_rows = conn.execute(t_query, t_params).fetchall()

            # Query inference frame latencies
            inf_query = (
                "SELECT timestamp_utc, preprocessing_ms, hailo_exec_ms, postprocessing_ms, total_latency_ms "
                "FROM inference_frames WHERE 1=1"
            )
            inf_params: List[Any] = []
            if start_time:
                inf_query += " AND timestamp_utc >= ?"
                inf_params.append(start_time)
            if end_time:
                inf_query += " AND timestamp_utc <= ?"
                inf_params.append(end_time)
            inf_query += " ORDER BY timestamp_utc ASC, id ASC LIMIT ?"
            inf_params.append(limit)
            inf_rows = conn.execute(inf_query, inf_params).fetchall()
        finally:
            conn.close()

        # Group telemetry by timestamp
        grouped_telemetry: Dict[str, Dict[str, float]] = collections.defaultdict(dict)
        for ts, metric, val in t_rows:
            if val is not None:
                grouped_telemetry[ts][metric] = val

        # Group inference by timestamp
        grouped_inference: Dict[str, List[Tuple[float, float, float, float]]] = collections.defaultdict(list)
        for ts, pre_ms, exec_ms, post_ms, tot_ms in inf_rows:
            grouped_inference[ts].append((pre_ms, exec_ms, post_ms, tot_ms))

        all_timestamps = sorted(set(grouped_telemetry.keys()) | set(grouped_inference.keys()))
        if not all_timestamps:
            session.close()
            return session

        first_ts_iso = all_timestamps[0]
        try:
            t0 = datetime.fromisoformat(first_ts_iso.replace("Z", "+00:00")).timestamp()
        except Exception:
            t0 = 0.0

        for ts in all_timestamps:
            try:
                curr_t = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                rel_sec = max(0.0, curr_t - t0)
            except Exception:
                rel_sec = 0.0

            m = grouped_telemetry.get(ts, {})
            inf_list = grouped_inference.get(ts, [])

            ts0 = m.get("hailo_temp_ts0_c")
            ts1 = m.get("hailo_temp_ts1_c")
            tj = m.get("hailo_junction_temperature_c", m.get("hailo_temperature_c"))
            if tj is None and (ts0 is not None or ts1 is not None):
                tj = max(v for v in (ts0, ts1) if v is not None)

            clock = m.get("hailo_clock_frequency_mhz")
            lvl = m.get("hailo_throttling_level")
            throttling_level = int(lvl) if lvl is not None else None
            is_throttled = (throttling_level is not None and throttling_level >= 0) or (
                tj is not None and tj >= 104.0
            )

            cpu_load = m.get("cpu_utilisation_percent", m.get("cpu_util"))
            cpu_temp = m.get("cpu_temperature_c", m.get("hwmon_cpu_thermal_temp"))

            fan_rpm = m.get("hwmon_pwmfan_fan1_rpm")
            if fan_rpm is None:
                for k, v in m.items():
                    if "fan" in k and "rpm" in k:
                        fan_rpm = v
                        break

            # Compute latency percentiles if inference records are present for this second
            if inf_list:
                pre_sorted = sorted(x[0] for x in inf_list)
                exec_sorted = sorted(x[1] for x in inf_list)
                post_sorted = sorted(x[2] for x in inf_list)
                tot_sorted = sorted(x[3] for x in inf_list)
                n = len(inf_list)

                def _pct(arr: List[float], q: float) -> float:
                    idx = min(int(n * q), n - 1)
                    return round(arr[idx], 2)

                p = TrajectoryPoint(
                    timestamp_utc=ts,
                    monotonic_ts=0.0,
                    relative_seconds=rel_sec,
                    workload_name=workload_name,
                    ts0_c=ts0,
                    ts1_c=ts1,
                    tj_c=tj,
                    clock_mhz=clock,
                    throttling_level=throttling_level,
                    throttling_active=is_throttled,
                    npu_util_percent=m.get("hailo_utilization_percent"),
                    fps=float(len(inf_list)),
                    cpu_load_percent=cpu_load,
                    cpu_temp_c=cpu_temp,
                    fan_rpm=fan_rpm,
                    lat_pre_p50_ms=_pct(pre_sorted, 0.50),
                    lat_pre_p95_ms=_pct(pre_sorted, 0.95),
                    lat_pre_p99_ms=_pct(pre_sorted, 0.99),
                    lat_npu_p50_ms=_pct(exec_sorted, 0.50),
                    lat_npu_p95_ms=_pct(exec_sorted, 0.95),
                    lat_npu_p99_ms=_pct(exec_sorted, 0.99),
                    lat_post_p50_ms=_pct(post_sorted, 0.50),
                    lat_post_p95_ms=_pct(post_sorted, 0.95),
                    lat_post_p99_ms=_pct(post_sorted, 0.99),
                    lat_total_p50_ms=_pct(tot_sorted, 0.50),
                    lat_total_p95_ms=_pct(tot_sorted, 0.95),
                    lat_total_p99_ms=_pct(tot_sorted, 0.99),
                )
            else:
                p = TrajectoryPoint(
                    timestamp_utc=ts,
                    monotonic_ts=0.0,
                    relative_seconds=rel_sec,
                    workload_name=workload_name,
                    ts0_c=ts0,
                    ts1_c=ts1,
                    tj_c=tj,
                    clock_mhz=clock,
                    throttling_level=throttling_level,
                    throttling_active=is_throttled,
                    npu_util_percent=m.get("hailo_utilization_percent"),
                    fps=0.0,
                    cpu_load_percent=cpu_load,
                    cpu_temp_c=cpu_temp,
                    fan_rpm=fan_rpm,
                )
            session.add_point(p)

        session.close()
        return session


# Global singleton instance
_GLOBAL_TRAJECTORY_ENGINE: Optional[TrajectoryEngine] = None
_GLOBAL_LOCK = threading.Lock()


def get_trajectory_engine() -> TrajectoryEngine:
    """Return the global TrajectoryEngine singleton instance."""
    global _GLOBAL_TRAJECTORY_ENGINE
    with _GLOBAL_LOCK:
        if _GLOBAL_TRAJECTORY_ENGINE is None:
            _GLOBAL_TRAJECTORY_ENGINE = TrajectoryEngine()
        return _GLOBAL_TRAJECTORY_ENGINE
