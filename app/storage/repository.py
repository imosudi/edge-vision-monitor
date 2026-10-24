"""
Persistent telemetry repository with non-blocking batched writes,
time-series range queries, downsampling, automated retention pruning, and CSV export.
Configured for SQLite Write-Ahead Logging (WAL) mode with high-throughput concurrent reads.
"""

from __future__ import annotations

import csv
import io
import queue
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from app.core.logging_config import get_logger
from app.storage.database import (
    checkpoint_wal,
    get_connection,
    get_db_file_sizes,
    init_database,
)
from app.storage.downsampling import (
    downsample_bucket_aggregation,
    downsample_lttb,
    downsample_stride,
)
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
    and system events into SQLite in WAL mode, while servicing fast queries,
    query downsampling, automated retention pruning, and streaming CSV exports.
    """

    def __init__(
        self,
        db_path: str,
        batch_size: int = 50,
        flush_interval_seconds: float = 1.0,
        max_queue_size: int = 5000,
        retention_days: int = 7,
        retention_hours: Optional[float] = None,
        prune_interval_seconds: float = 3600.0,
        max_db_size_mb: Optional[float] = 500.0,
        read_only: bool = False,
    ):
        self._db_path = db_path
        self._read_only = read_only
        self._batch_size = max(1, batch_size)
        self._flush_interval = max(0.01, flush_interval_seconds)
        self._max_queue_size = max(1, max_queue_size)
        self._queue: queue.Queue[Tuple[str, Any]] = queue.Queue(maxsize=self._max_queue_size)

        # Retention parameters
        self._retention_hours = float(retention_hours) if retention_hours is not None else float(retention_days * 24.0)
        self._prune_interval_seconds = max(0.05, prune_interval_seconds)
        self._max_db_size_mb = max_db_size_mb

        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._write_lock = threading.Lock()

        # Telemetry ingestion and maintenance metrics
        self._dropped_samples_count = 0
        self._total_telemetry_enqueued = 0
        self._total_inference_enqueued = 0
        self._total_events_enqueued = 0
        self._total_committed_records = 0
        self._total_batches_committed = 0
        self._total_purged_records = 0
        self._last_prune_time = time.monotonic()
        self._last_prune_timestamp_utc: Optional[str] = None
        self._last_prune_summary: Dict[str, Any] = {}

        # Ensure database and WAL mode are initialised (writers only)
        if not self._read_only:
            init_database(self._db_path)

    def start(self) -> None:
        """Start the background batched writer and automated pruning thread."""
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._writer_loop, name="StorageWriterWorker", daemon=True
        )
        self._worker_thread.start()
        logger.info(
            "Storage background writer worker started (batch_size=%d, flush_interval=%.2fs, retention=%.1fh)",
            self._batch_size,
            self._flush_interval,
            self._retention_hours,
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Stop background worker and flush any pending write items."""
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
        self._drain_remaining()
        logger.info("Storage repository stopped cleanly")

    # -------------------------------------------------------------------------
    # Non-blocking Asynchronous Enqueue API
    # -------------------------------------------------------------------------

    def enqueue_telemetry(self, samples: List[TelemetrySample]) -> bool:
        """
        Enqueue telemetry samples for asynchronous batched persistence.
        Completely non-blocking: drops samples and logs warning if queue is full.
        """
        if not samples:
            return True
        try:
            self._queue.put_nowait(("telemetry", samples))
            self._total_telemetry_enqueued += len(samples)
            return True
        except queue.Full:
            self._dropped_samples_count += len(samples)
            if self._dropped_samples_count % 50 == 0 or self._dropped_samples_count <= len(samples):
                logger.warning(
                    "Storage queue full! Dropped %d telemetry samples (cumulative dropped: %d)",
                    len(samples),
                    self._dropped_samples_count,
                )
            return False

    def enqueue_inference(
        self, frame: InferenceFrameRecord, detections: List[DetectionRecord]
    ) -> bool:
        """
        Enqueue inference frame record and associated object detections.
        Completely non-blocking: never delays the computer vision pipeline.
        """
        try:
            self._queue.put_nowait(("inference", (frame, detections)))
            self._total_inference_enqueued += 1
            return True
        except queue.Full:
            self._dropped_samples_count += 1
            logger.warning("Storage queue full! Dropped inference frame record")
            return False

    def enqueue_event(self, event: SystemEventRecord) -> bool:
        """
        Enqueue system lifecycle or diagnostic event.
        Completely non-blocking.
        """
        try:
            self._queue.put_nowait(("event", event))
            self._total_events_enqueued += 1
            return True
        except queue.Full:
            logger.warning("Storage queue full! Dropped system event")
            return False

    # -------------------------------------------------------------------------
    # Worker Thread and Batched Commits
    # -------------------------------------------------------------------------

    def _writer_loop(self) -> None:
        """
        Continuously pulls items from bounded queue, executes batched transactions,
        and triggers periodic automated retention pruning.
        """
        conn = get_connection(self._db_path)
        last_flush = time.monotonic()
        pending_telemetry: List[TelemetrySample] = []
        pending_inference: List[Tuple[InferenceFrameRecord, List[DetectionRecord]]] = []
        pending_events: List[SystemEventRecord] = []
        total_pending = 0

        try:
            while not self._stop_event.is_set():
                if total_pending > 0:
                    timeout = max(0.01, min(0.1, self._flush_interval - (time.monotonic() - last_flush)))
                else:
                    timeout = max(0.01, min(0.1, self._prune_interval_seconds))
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

                # Batch commit threshold check (count or time-based)
                if total_pending >= self._batch_size or (total_pending > 0 and (now - last_flush) >= self._flush_interval):
                    self._commit_batch(conn, pending_telemetry, pending_inference, pending_events)
                    pending_telemetry.clear()
                    pending_inference.clear()
                    pending_events.clear()
                    last_flush = now

                # Automated periodic retention pruning check
                if (now - self._last_prune_time) >= self._prune_interval_seconds:
                    self._last_prune_time = now
                    try:
                        summary = self._run_retention_prune_internal(conn)
                        self._last_prune_summary = summary
                        self._last_prune_timestamp_utc = summary.get("timestamp_utc")
                        self._total_purged_records += summary.get("total_purged", 0)
                    except Exception as pe:
                        logger.error("Automated retention pruning encountered an error: %s", pe)

        except Exception as e:
            logger.error("Fatal error in storage writer loop: %s", e, exc_info=True)
        finally:
            if pending_telemetry or pending_inference or pending_events:
                self._commit_batch(conn, pending_telemetry, pending_inference, pending_events)
            conn.close()

    def _drain_remaining(self) -> None:
        """Final drain on shutdown: commits all remaining queue items to SQLite."""
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
        """Write records to SQLite within a single immediate transaction."""
        committed_count = 0
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
                        committed_count += len(telemetry)

                    if inference:
                        for frame, detections in inference:
                            conn.execute(
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
                            committed_count += 1
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
                                committed_count += len(detections)

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
                        committed_count += len(events)

            self._total_committed_records += committed_count
            self._total_batches_committed += 1
        except Exception as e:
            logger.error("Failed to commit SQLite batch: %s", e, exc_info=True)

    # -------------------------------------------------------------------------
    # Automated Retention Pruning
    # -------------------------------------------------------------------------

    def _run_retention_prune_internal(
        self, conn: sqlite3.Connection, retention_hours: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Internal prune routine running inside the writer connection or maintenance call.
        Enforces time-based cutoff and optional database file size constraints.
        """
        hours = retention_hours if retention_hours is not None else self._retention_hours
        cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_utc = cutoff_dt.isoformat()
        now_utc = datetime.now(timezone.utc).isoformat()

        with self._write_lock:
            with conn:
                c1 = conn.execute("DELETE FROM telemetry_samples WHERE timestamp_utc < ?", (cutoff_utc,))
                c2 = conn.execute("DELETE FROM inference_frames WHERE timestamp_utc < ?", (cutoff_utc,))
                c3 = conn.execute("DELETE FROM detections WHERE timestamp_utc < ?", (cutoff_utc,))
                c4 = conn.execute("DELETE FROM system_events WHERE timestamp_utc < ?", (cutoff_utc,))
                total_deleted = c1.rowcount + c2.rowcount + c3.rowcount + c4.rowcount

            # Size-based pruning check
            size_pruned = 0
            if self._max_db_size_mb is not None and self._max_db_size_mb > 0:
                sizes = get_db_file_sizes(self._db_path)
                current_mb = sizes["total_bytes"] / (1024.0 * 1024.0)
                if current_mb > self._max_db_size_mb:
                    logger.warning(
                        "Database size (%.1f MB) exceeds limit (%.1f MB). Pruning oldest records...",
                        current_mb,
                        self._max_db_size_mb,
                    )
                    with conn:
                        # Prune oldest 15% of records
                        sp1 = conn.execute(
                            """
                            DELETE FROM telemetry_samples WHERE id IN (
                                SELECT id FROM telemetry_samples ORDER BY id ASC LIMIT 2000
                            )
                            """
                        )
                        sp2 = conn.execute(
                            """
                            DELETE FROM inference_frames WHERE id IN (
                                SELECT id FROM inference_frames ORDER BY id ASC LIMIT 1000
                            )
                            """
                        )
                        size_pruned = sp1.rowcount + sp2.rowcount
                    # Checkpoint WAL to release pages
                    checkpoint_wal(self._db_path, "TRUNCATE")

        total_purged = total_deleted + size_pruned
        if total_purged > 0:
            logger.info(
                "Retention pruning completed: purged %d records older than %s (retention: %.1fh, size_pruned: %d)",
                total_deleted,
                cutoff_utc,
                hours,
                size_pruned,
            )

        return {
            "purged_telemetry": c1.rowcount,
            "purged_inference": c2.rowcount,
            "purged_detections": c3.rowcount,
            "purged_events": c4.rowcount,
            "purged_oversize": size_pruned,
            "total_purged": total_purged,
            "cutoff_utc": cutoff_utc,
            "timestamp_utc": now_utc,
            "retention_hours": hours,
        }

    def prune_retention(self, retention_hours: Optional[float] = None) -> Dict[str, Any]:
        """
        Public method to manually trigger automated retention pruning.
        Can override configured retention hours on demand.
        """
        conn = get_connection(self._db_path)
        try:
            summary = self._run_retention_prune_internal(conn, retention_hours=retention_hours)
            self._last_prune_summary = summary
            self._last_prune_timestamp_utc = summary.get("timestamp_utc")
            self._total_purged_records += summary.get("total_purged", 0)
            return summary
        finally:
            conn.close()

    def purge_older_than(self, retention_days: int) -> int:
        """
        Backwards-compatible retention purge method.
        Purges records older than specified number of days.
        """
        summary = self.prune_retention(retention_hours=retention_days * 24.0)
        return summary.get("total_purged", 0)

    # -------------------------------------------------------------------------
    # Time-Series Query API with Downsampling
    # -------------------------------------------------------------------------

    def query_telemetry_history(
        self,
        metric_name: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 500,
        downsample: int = 1,
        target_points: Optional[int] = None,
        method: str = "stride",
    ) -> List[Dict[str, Any]]:
        """
        Query historical time-series telemetry records with optional downsampling.

        Supports:
        - Strided downsampling ('stride')
        - Largest-Triangle-Three-Buckets ('lttb')
        - Time-window bucket aggregation ('bucket')
        """
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
        # Fetch sufficient rows to downsample accurately
        fetch_limit = min(limit * max(1, downsample) * (5 if target_points else 1), 20000)
        params.append(fetch_limit)

        conn = get_connection(self._db_path)
        try:
            cursor = conn.execute(query, params)
            rows = [dict(r) for r in cursor.fetchall()]
            # Return in chronological order (oldest to newest)
            rows.reverse()

            if not rows:
                return []

            # Apply requested downsampling algorithm
            if target_points is not None and target_points > 0 and len(rows) > target_points:
                if method.lower() == "lttb":
                    return downsample_lttb(rows, target_points=target_points)
                elif method.lower() == "bucket":
                    return downsample_bucket_aggregation(rows, target_points=target_points)
                else:
                    step = max(1, len(rows) // target_points)
                    return downsample_stride(rows, stride=step)

            if downsample > 1:
                return downsample_stride(rows, stride=downsample)

            if len(rows) > limit:
                return rows[-limit:]

            return rows
        finally:
            conn.close()

    def query_downsampled_metrics(
        self,
        metric_name: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        target_points: int = 100,
        method: str = "lttb",
    ) -> List[Dict[str, Any]]:
        """
        High-performance downsampled query explicitly tailored for responsive charts.
        """
        return self.query_telemetry_history(
            metric_name=metric_name,
            start_time=start_time,
            end_time=end_time,
            limit=target_points * 2,
            target_points=target_points,
            method=method,
        )

    def query_inference_history(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query historical inference frame performance records in chronological order."""
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
        """Query historical object detection events in chronological order."""
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
        params.append(min(limit, 2000))

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

    def reset_history(
        self,
        clear_telemetry: bool = True,
        clear_inference: bool = True,
        clear_detections: bool = True,
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
                checkpoint_wal(self._db_path, "TRUNCATE")
                return deleted
            finally:
                conn.close()

    # -------------------------------------------------------------------------
    # CSV Export API (String and Chunked Generator Streaming)
    # -------------------------------------------------------------------------

    def export_telemetry_csv(
        self,
        metric_name: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 50000,
    ) -> str:
        """Export telemetry samples as a CSV formatted string."""
        return "".join(
            self.stream_telemetry_csv(
                metric_name=metric_name,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
            )
        )

    def stream_telemetry_csv(
        self,
        metric_name: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 50000,
        chunk_size: int = 2000,
    ) -> Generator[str, None, None]:
        """Stream telemetry samples chunk-by-chunk for memory-efficient HTTP delivery."""
        query = (
            "SELECT timestamp_utc, metric_name, value, unit, source, availability_status "
            "FROM telemetry_samples WHERE 1=1"
        )
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

        query += " ORDER BY id ASC LIMIT ?"
        params.append(limit)

        header = "timestamp_utc,metric_name,value,unit,source,availability_status\r\n"
        yield header

        conn = get_connection(self._db_path)
        try:
            cursor = conn.execute(query, params)
            output = io.StringIO()
            writer = csv.writer(output, lineterminator="\r\n")

            while True:
                rows = cursor.fetchmany(chunk_size)
                if not rows:
                    break
                for row in rows:
                    writer.writerow([row[0], row[1], row[2], row[3], row[4], row[5]])
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)
        finally:
            conn.close()

    def export_detections_csv(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        class_name: Optional[str] = None,
        limit: int = 50000,
    ) -> str:
        """Export detections history as a CSV formatted string."""
        return "".join(
            self.stream_detections_csv(
                start_time=start_time,
                end_time=end_time,
                class_name=class_name,
                limit=limit,
            )
        )

    def stream_detections_csv(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        class_name: Optional[str] = None,
        limit: int = 50000,
        chunk_size: int = 2000,
    ) -> Generator[str, None, None]:
        """Stream object detection records chunk-by-chunk."""
        query = (
            "SELECT timestamp_utc, frame_seq, class_id, class_name, confidence, "
            "box_xmin, box_ymin, box_xmax, box_ymax FROM detections WHERE 1=1"
        )
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

        query += " ORDER BY id ASC LIMIT ?"
        params.append(limit)

        header = "timestamp_utc,frame_seq,class_id,class_name,confidence,box_xmin,box_ymin,box_xmax,box_ymax\r\n"
        yield header

        conn = get_connection(self._db_path)
        try:
            cursor = conn.execute(query, params)
            output = io.StringIO()
            writer = csv.writer(output, lineterminator="\r\n")

            while True:
                rows = cursor.fetchmany(chunk_size)
                if not rows:
                    break
                for row in rows:
                    writer.writerow(list(row))
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)
        finally:
            conn.close()

    def export_waveforms_csv(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 50000,
    ) -> str:
        """
        Export complete multi-channel telemetry sensor and inference waveforms
        as a unified time-series CSV dataset.
        """
        return "".join(
            self.stream_waveforms_csv(
                start_time=start_time,
                end_time=end_time,
                limit=limit,
            )
        )

    def stream_waveforms_csv(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 50000,
    ) -> Generator[str, None, None]:
        """
        Stream multi-channel time-aligned waveforms joining hardware telemetry
        and computer vision inference metrics into unified rows.
        """
        conn = get_connection(self._db_path)
        try:
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

            inf_query = (
                "SELECT timestamp_utc, preprocessing_ms, hailo_exec_ms, postprocessing_ms, "
                "total_latency_ms, detections_count FROM inference_frames WHERE 1=1"
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

        if not ts_map:
            yield "timestamp_utc,latency_prep_ms,latency_exec_ms,latency_post_ms,latency_total_ms,detections_count,cpu_temp,mem_util,cpu_util\r\n"
            return

        all_keys = sorted({k for data in ts_map.values() for k in data.keys()})
        fieldnames = ["timestamp_utc"] + all_keys

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\r\n")
        writer.writeheader()
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        chunk_count = 0
        for ts, data in sorted(ts_map.items()):
            row_dict = {"timestamp_utc": ts}
            row_dict.update(data)
            writer.writerow(row_dict)
            chunk_count += 1
            if chunk_count >= 1000:
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)
                chunk_count = 0

        if output.tell() > 0:
            yield output.getvalue()

    def export_trajectory_csv(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        workload_name: str = "historical",
        limit: int = 50000,
    ) -> str:
        """
        Export structured time-series trajectory (timestamp, TS0, TS1, Tj, clock,
        throttling level, FPS, CPU load, fan RPM, latency percentiles) as a CSV string.
        """
        from app.telemetry.trajectory import get_trajectory_engine

        engine = get_trajectory_engine()
        session = engine.reconstruct_from_repository(
            repository=self,
            start_time=start_time,
            end_time=end_time,
            workload_name=workload_name,
            limit=limit,
        )
        return session.export_csv()

    def export_trajectory_json(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        workload_name: str = "historical",
        limit: int = 50000,
    ) -> Dict[str, Any]:
        """
        Export structured time-series trajectory as a JSON-serializable dictionary.
        """
        from app.telemetry.trajectory import get_trajectory_engine

        engine = get_trajectory_engine()
        session = engine.reconstruct_from_repository(
            repository=self,
            start_time=start_time,
            end_time=end_time,
            workload_name=workload_name,
            limit=limit,
        )
        return session.export_json()

    def stream_trajectory_csv(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        workload_name: str = "historical",
        limit: int = 50000,
    ) -> Generator[str, None, None]:
        """
        Stream structured time-series trajectory chunk by chunk in CSV format.
        """
        from app.telemetry.trajectory import get_trajectory_engine

        engine = get_trajectory_engine()
        session = engine.reconstruct_from_repository(
            repository=self,
            start_time=start_time,
            end_time=end_time,
            workload_name=workload_name,
            limit=limit,
        )
        for chunk in engine.stream_csv(session_id=session.session_id):
            yield chunk

    # -------------------------------------------------------------------------
    # Diagnostics & Storage Statistics
    # -------------------------------------------------------------------------

    def get_storage_stats(self) -> Dict[str, Any]:
        """
        Return comprehensive storage metrics: WAL file sizes, record counts,
        queue capacity, dropped sample metrics, and automated retention history.
        """
        conn = get_connection(self._db_path)
        try:
            c1 = conn.execute("SELECT count(*) FROM telemetry_samples").fetchone()[0]
            c2 = conn.execute("SELECT count(*) FROM inference_frames").fetchone()[0]
            c3 = conn.execute("SELECT count(*) FROM detections").fetchone()[0]
            c4 = conn.execute("SELECT count(*) FROM system_events").fetchone()[0]
            cur_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        finally:
            conn.close()

        file_sizes = get_db_file_sizes(self._db_path)

        return {
            "db_path": self._db_path,
            "journal_mode": str(cur_mode).lower(),
            "file_sizes": file_sizes,
            "total_records": {
                "telemetry_samples": c1,
                "inference_frames": c2,
                "detections": c3,
                "system_events": c4,
                "total": c1 + c2 + c3 + c4,
            },
            "queue": {
                "pending_items": self._queue.qsize(),
                "max_size": self._max_queue_size,
                "dropped_samples": self._dropped_samples_count,
            },
            "ingestion_totals": {
                "telemetry_enqueued": self._total_telemetry_enqueued,
                "inference_enqueued": self._total_inference_enqueued,
                "events_enqueued": self._total_events_enqueued,
                "committed_records": self._total_committed_records,
                "batches_committed": self._total_batches_committed,
            },
            "retention": {
                "retention_hours": self._retention_hours,
                "prune_interval_seconds": self._prune_interval_seconds,
                "max_db_size_mb": self._max_db_size_mb,
                "total_purged_records": self._total_purged_records,
                "last_prune_timestamp_utc": self._last_prune_timestamp_utc,
                "last_prune_summary": self._last_prune_summary,
            },
        }
