"""
Persistent telemetry repository with non-blocking batched writes,
time-series range queries, downsampling, retention pruning, and CSV export.
"""

from __future__ import annotations

import csv
import io
import queue
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging_config import get_logger
from app.storage.database import get_connection, init_database
from app.storage.models import (
    DetectionRecord,
    InferenceFrameRecord,
    SystemEventRecord,
    TelemetrySample,
)

logger = get_logger("STORAGE.REPO")


class TelemetryRepository:
    """
    Manages non-blocking batched ingestion of telemetry, inference frames, detections,
    and system events into SQLite, while servicing fast queries from API and dashboard.
    """

    def __init__(
        self,
        db_path: str,
        batch_size: int = 50,
        flush_interval_seconds: float = 1.0,
        max_queue_size: int = 5000,
    ):
        self._db_path = db_path
        self._batch_size = batch_size
        self._flush_interval = flush_interval_seconds
        self._queue: queue.Queue[Tuple[str, Any]] = queue.Queue(maxsize=max_queue_size)
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._dropped_samples_count = 0
        self._write_lock = threading.Lock()

        # Ensure database is initialised
        init_database(self._db_path)

    def start(self) -> None:
        """Start the background batched writer thread."""
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._writer_loop, name="StorageWriterWorker", daemon=True
        )
        self._worker_thread.start()
        logger.info("Storage background writer worker started")

    def stop(self, timeout: float = 5.0) -> None:
        """Stop background worker and flush any pending write items."""
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
        self._drain_remaining()
        logger.info("Storage repository stopped cleanly")

    def enqueue_telemetry(self, samples: List[TelemetrySample]) -> bool:
        """Enqueue telemetry samples for asynchronous batched persistence."""
        try:
            self._queue.put_nowait(("telemetry", samples))
            return True
        except queue.Full:
            self._dropped_samples_count += len(samples)
            logger.warning(
                "Storage queue full! Dropped %d telemetry samples (total dropped: %d)",
                len(samples),
                self._dropped_samples_count,
            )
            return False

    def enqueue_inference(
        self, frame: InferenceFrameRecord, detections: List[DetectionRecord]
    ) -> bool:
        """Enqueue inference frame record and associated object detections."""
        try:
            self._queue.put_nowait(("inference", (frame, detections)))
            return True
        except queue.Full:
            self._dropped_samples_count += 1
            logger.warning("Storage queue full! Dropped inference frame record")
            return False

    def enqueue_event(self, event: SystemEventRecord) -> bool:
        """Enqueue system lifecycle or diagnostic event."""
        try:
            self._queue.put_nowait(("event", event))
            return True
        except queue.Full:
            logger.warning("Storage queue full! Dropped system event")
            return False

    def _writer_loop(self) -> None:
        """Continuously pulls items from queue and flushes in SQLite transactions."""
        conn = get_connection(self._db_path)
        last_flush = time.monotonic()
        pending_telemetry: List[TelemetrySample] = []
        pending_inference: List[Tuple[InferenceFrameRecord, List[DetectionRecord]]] = []
        pending_events: List[SystemEventRecord] = []

        try:
            while not self._stop_event.is_set():
                timeout = max(0.05, self._flush_interval - (time.monotonic() - last_flush))
                try:
                    item_type, item_data = self._queue.get(timeout=timeout)
                    if item_type == "telemetry":
                        pending_telemetry.extend(item_data)
                    elif item_type == "inference":
                        pending_inference.append(item_data)
                    elif item_type == "event":
                        pending_events.append(item_data)
                    self._queue.task_done()
                except queue.Empty:
                    pass

                total_pending = len(pending_telemetry) + len(pending_inference) + len(pending_events)
                now = time.monotonic()
                if total_pending >= self._batch_size or (total_pending > 0 and (now - last_flush) >= self._flush_interval):
                    self._commit_batch(conn, pending_telemetry, pending_inference, pending_events)
                    pending_telemetry.clear()
                    pending_inference.clear()
                    pending_events.clear()
                    last_flush = now

        except Exception as e:
            logger.error("Error in storage writer loop: %s", e, exc_info=True)
        finally:
            if pending_telemetry or pending_inference or pending_events:
                self._commit_batch(conn, pending_telemetry, pending_inference, pending_events)
            conn.close()

    def _drain_remaining(self) -> None:
        """Final drain on shutdown."""
        conn = get_connection(self._db_path)
        telemetry: List[TelemetrySample] = []
        inference: List[Tuple[InferenceFrameRecord, List[DetectionRecord]]] = []
        events: List[SystemEventRecord] = []

        while not self._queue.empty():
            try:
                item_type, item_data = self._queue.get_nowait()
                if item_type == "telemetry":
                    telemetry.extend(item_data)
                elif item_type == "inference":
                    inference.append(item_data)
                elif item_type == "event":
                    events.append(item_data)
                self._queue.task_done()
            except queue.Empty:
                break

        if telemetry or inference or events:
            self._commit_batch(conn, telemetry, inference, events)
        conn.close()

    def _commit_batch(
        self,
        conn: sqlite3.Connection,
        telemetry: List[TelemetrySample],
        inference: List[Tuple[InferenceFrameRecord, List[DetectionRecord]]],
        events: List[SystemEventRecord],
    ) -> None:
        """Write records to SQLite within a single transaction."""
        try:
            with self._write_lock:
                with conn:
                    if telemetry:
                        conn.executemany(
                            """
                            INSERT INTO telemetry_samples (
                                timestamp_utc, monotonic_ts, metric_name, value, unit,
                                source, availability_status, error_message
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            [
                                (
                                    s.timestamp_utc,
                                    s.monotonic_ts,
                                    s.metric_name,
                                    s.value,
                                    s.unit,
                                    s.source,
                                    s.availability_status,
                                    s.error_message,
                                )
                                for s in telemetry
                            ],
                        )

                    if inference:
                        for frame, detections in inference:
                            cur = conn.execute(
                                """
                                INSERT INTO inference_frames (
                                    frame_seq, source_id, timestamp_utc, acquisition_ms,
                                    preprocessing_ms, hailo_exec_ms, postprocessing_ms,
                                    total_latency_ms, detections_count, dropped, error_status
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    frame.frame_seq,
                                    frame.source_id,
                                    frame.timestamp_utc,
                                    frame.acquisition_ms,
                                    frame.preprocessing_ms,
                                    frame.hailo_exec_ms,
                                    frame.postprocessing_ms,
                                    frame.total_latency_ms,
                                    frame.detections_count,
                                    1 if frame.dropped else 0,
                                    frame.error_status,
                                ),
                            )
                            if detections:
                                conn.executemany(
                                    """
                                    INSERT INTO detections (
                                        frame_seq, timestamp_utc, class_id, class_name,
                                        confidence, box_xmin, box_ymin, box_xmax, box_ymax
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    [
                                        (
                                            d.frame_seq,
                                            d.timestamp_utc,
                                            d.class_id,
                                            d.class_name,
                                            d.confidence,
                                            d.box_xmin,
                                            d.box_ymin,
                                            d.box_xmax,
                                            d.box_ymax,
                                        )
                                        for d in detections
                                    ],
                                )

                    if events:
                        conn.executemany(
                            """
                            INSERT INTO system_events (
                                timestamp_utc, event_type, severity, component,
                                message, details_json
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            [
                                (
                                    e.timestamp_utc,
                                    e.event_type,
                                    e.severity,
                                    e.component,
                                    e.message,
                                    e.details_json,
                                )
                                for e in events
                            ],
                        )
        except Exception as e:
            logger.error("Failed to commit SQLite batch: %s", e, exc_info=True)

    # -------------------------------------------------------------------------
    # Query API
    # -------------------------------------------------------------------------

    def query_telemetry_history(
        self,
        metric_name: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 500,
        downsample: int = 1,
    ) -> List[Dict[str, Any]]:
        """Query historical time-series telemetry records."""
        query = "SELECT * FROM telemetry_samples WHERE 1=1"
        params: List[Any] = []

        if metric_name:
            query += " AND metric_name = ?"
            params.append(metric_name)
        if start_time:
            query += " AND timestamp_utc >= ?"
            params.append(start_time)
        if end_time:
            query += " AND timestamp_utc <= ?"
            params.append(end_time)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(min(limit * max(1, downsample), 10000))

        conn = get_connection(self._db_path)
        try:
            cursor = conn.execute(query, params)
            rows = [dict(r) for r in cursor.fetchall()]
            # Apply downsampling if requested
            if downsample > 1 and rows:
                rows = rows[::downsample]
            # Return chronological order
            rows.reverse()
            return rows
        finally:
            conn.close()

    def query_inference_history(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query historical inference frame performance records."""
        query = "SELECT * FROM inference_frames WHERE 1=1"
        params: List[Any] = []

        if start_time:
            query += " AND timestamp_utc >= ?"
            params.append(start_time)
        if end_time:
            query += " AND timestamp_utc <= ?"
            params.append(end_time)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(min(limit, 5000))

        conn = get_connection(self._db_path)
        try:
            cursor = conn.execute(query, params)
            rows = [dict(r) for r in cursor.fetchall()]
            rows.reverse()
            return rows
        finally:
            conn.close()

    def query_detections_history(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        class_name: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query historical object detection events."""
        query = "SELECT * FROM detections WHERE 1=1"
        params: List[Any] = []

        if start_time:
            query += " AND timestamp_utc >= ?"
            params.append(start_time)
        if end_time:
            query += " AND timestamp_utc <= ?"
            params.append(end_time)
        if class_name:
            query += " AND class_name = ?"
            params.append(class_name)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(min(limit, 1000))

        conn = get_connection(self._db_path)
        try:
            cursor = conn.execute(query, params)
            rows = [dict(r) for r in cursor.fetchall()]
            rows.reverse()
            return rows
        finally:
            conn.close()

    def query_events(
        self,
        start_time: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query recent system lifecycle, health, and error events."""
        query = "SELECT * FROM system_events WHERE 1=1"
        params: List[Any] = []

        if start_time:
            query += " AND timestamp_utc >= ?"
            params.append(start_time)
        if severity:
            query += " AND severity = ?"
            params.append(severity)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(min(limit, 500))

        conn = get_connection(self._db_path)
        try:
            cursor = conn.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    def purge_older_than(self, retention_days: int) -> int:
        """Purge telemetry and frame records older than the retention threshold."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        with self._write_lock:
            conn = get_connection(self._db_path)
            deleted = 0
            try:
                with conn:
                    c1 = conn.execute("DELETE FROM telemetry_samples WHERE timestamp_utc < ?", (cutoff,))
                    c2 = conn.execute("DELETE FROM inference_frames WHERE timestamp_utc < ?", (cutoff,))
                    c3 = conn.execute("DELETE FROM detections WHERE timestamp_utc < ?", (cutoff,))
                    c4 = conn.execute("DELETE FROM system_events WHERE timestamp_utc < ?", (cutoff,))
                    deleted = c1.rowcount + c2.rowcount + c3.rowcount + c4.rowcount
                logger.info("Purged %d records older than %s (%d days)", deleted, cutoff, retention_days)
                return deleted
            finally:
                conn.close()

    def reset_history(
        self, clear_telemetry: bool = True, clear_inference: bool = True, clear_detections: bool = True
    ) -> Dict[str, int]:
        """
        Delete persisted telemetry samples, inference frames, and detections from SQLite
        and discard pending items in the ingestion queue.
        """
        with self._write_lock:
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except (queue.Empty, ValueError):
                    break

            conn = get_connection(self._db_path)
            deleted = {"telemetry": 0, "inference_frames": 0, "detections": 0}
            try:
                with conn:
                    if clear_telemetry:
                        c1 = conn.execute("DELETE FROM telemetry_samples")
                        deleted["telemetry"] = c1.rowcount
                    if clear_inference:
                        c2 = conn.execute("DELETE FROM inference_frames")
                        deleted["inference_frames"] = c2.rowcount
                    if clear_detections:
                        c3 = conn.execute("DELETE FROM detections")
                        deleted["detections"] = c3.rowcount
                logger.info("Reset history completed: %s", deleted)
                return deleted
            finally:
                conn.close()

    def export_telemetry_csv(
        self, metric_name: Optional[str] = None, limit: int = 5000
    ) -> str:
        """Export telemetry samples as a CSV formatted string."""
        samples = self.query_telemetry_history(metric_name=metric_name, limit=limit)
        output = io.StringIO()
        if not samples:
            return "timestamp_utc,metric_name,value,unit,source,availability_status\n"
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "timestamp_utc",
                "metric_name",
                "value",
                "unit",
                "source",
                "availability_status",
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(samples)
        return output.getvalue()

    def export_detections_csv(self, limit: int = 5000) -> str:
        """Export detections history as a CSV formatted string."""
        dets = self.query_detections_history(limit=limit)
        output = io.StringIO()
        if not dets:
            return "timestamp_utc,frame_seq,class_id,class_name,confidence,box_xmin,box_ymin,box_xmax,box_ymax\n"
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "timestamp_utc",
                "frame_seq",
                "class_id",
                "class_name",
                "confidence",
                "box_xmin",
                "box_ymin",
                "box_xmax",
                "box_ymax",
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(dets)
        return output.getvalue()

    def export_waveforms_csv(self, limit: int = 5000) -> str:
        """
        Export complete multi-channel telemetry sensor and inference waveforms
        as a unified time-series CSV dataset.
        """
        conn = get_connection(self._db_path)
        try:
            t_rows = conn.execute(
                """
                SELECT timestamp_utc, metric_name, value
                FROM telemetry_samples
                ORDER BY timestamp_utc ASC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

            inf_rows = conn.execute(
                """
                SELECT timestamp_utc, preprocessing_ms, hailo_exec_ms, postprocessing_ms, total_latency_ms, detections_count
                FROM inference_frames
                ORDER BY timestamp_utc ASC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        finally:
            conn.close()

        ts_map: Dict[str, Dict[str, Any]] = {}
        for row in t_rows:
            ts, m_name, val = row[0], row[1], row[2]
            if ts not in ts_map:
                ts_map[ts] = {}
            ts_map[ts][m_name] = val

        for row in inf_rows:
            ts = row[0]
            if ts not in ts_map:
                ts_map[ts] = {}
            ts_map[ts]["latency_prep_ms"] = row[1]
            ts_map[ts]["latency_exec_ms"] = row[2]
            ts_map[ts]["latency_post_ms"] = row[3]
            ts_map[ts]["latency_total_ms"] = row[4]
            ts_map[ts]["detections_count"] = row[5]

        output = io.StringIO()
        if not ts_map:
            return "timestamp_utc,latency_prep_ms,latency_exec_ms,latency_post_ms,latency_total_ms,detections_count,cpu_temp,mem_util,cpu_util\n"

        all_keys = sorted({k for data in ts_map.values() for k in data.keys()})
        fieldnames = ["timestamp_utc"] + all_keys
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for ts, data in sorted(ts_map.items()):
            row_dict = {"timestamp_utc": ts}
            row_dict.update(data)
            writer.writerow(row_dict)
        return output.getvalue()
