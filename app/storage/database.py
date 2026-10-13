"""
SQLite database connection management, WAL mode configuration, and schema migration.
Strictly configured for non-blocking concurrent reads and batched writes.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Dict, Tuple

from app.core.logging_config import get_logger

logger = get_logger("STORAGE.DB")

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 10000;
PRAGMA foreign_keys = ON;
PRAGMA wal_autocheckpoint = 1000;
PRAGMA cache_size = -64000;
PRAGMA temp_store = MEMORY;

CREATE TABLE IF NOT EXISTS telemetry_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc TEXT NOT NULL,
    monotonic_ts REAL NOT NULL,
    metric_name TEXT NOT NULL,
    value REAL,
    unit TEXT NOT NULL,
    source TEXT NOT NULL,
    availability_status TEXT NOT NULL,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_telemetry_ts_metric 
    ON telemetry_samples (timestamp_utc, metric_name);
CREATE INDEX IF NOT EXISTS idx_telemetry_metric_ts 
    ON telemetry_samples (metric_name, timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_telemetry_metric 
    ON telemetry_samples (metric_name);

CREATE TABLE IF NOT EXISTS inference_frames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    frame_seq INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    acquisition_ms REAL NOT NULL,
    preprocessing_ms REAL NOT NULL,
    hailo_exec_ms REAL NOT NULL,
    postprocessing_ms REAL NOT NULL,
    total_latency_ms REAL NOT NULL,
    detections_count INTEGER NOT NULL,
    dropped INTEGER NOT NULL DEFAULT 0,
    error_status TEXT
);

CREATE INDEX IF NOT EXISTS idx_inference_ts 
    ON inference_frames (timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_inference_seq 
    ON inference_frames (frame_seq);

CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    frame_seq INTEGER NOT NULL,
    timestamp_utc TEXT NOT NULL,
    class_id INTEGER NOT NULL,
    class_name TEXT NOT NULL,
    confidence REAL NOT NULL,
    box_xmin REAL NOT NULL,
    box_ymin REAL NOT NULL,
    box_xmax REAL NOT NULL,
    box_ymax REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_detections_ts 
    ON detections (timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_detections_class_ts 
    ON detections (class_name, timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_detections_class 
    ON detections (class_name);

CREATE TABLE IF NOT EXISTS system_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    component TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_ts 
    ON system_events (timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_events_sev 
    ON system_events (severity);
"""


def init_database(db_path: str) -> None:
    """
    Ensure the parent directory exists and execute the schema creation statements.
    Configures SQLite in Write-Ahead-Logging (WAL) mode for concurrent read/write operations.
    """
    path_obj = Path(db_path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path, timeout=15.0) as conn:
        conn.executescript(SCHEMA_SQL)
        # Verify WAL mode is active
        cur = conn.execute("PRAGMA journal_mode;")
        row = cur.fetchone()
        journal_mode = row[0].lower() if row else "unknown"
        if journal_mode != "wal":
            logger.warning("Database journal mode is '%s' instead of 'wal'", journal_mode)
        conn.commit()

    logger.info("Database initialised in WAL mode at '%s'", db_path)


def get_connection(db_path: str) -> sqlite3.Connection:
    """
    Get a new configured SQLite connection with row factory, WAL mode, and 10s busy timeout.
    Enables dictionary-like row access and memory page caching.
    """
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 10000;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA cache_size = -64000;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    return conn


def checkpoint_wal(db_path: str, mode: str = "PASSIVE") -> Tuple[int, int, int]:
    """
    Execute a Write-Ahead Log checkpoint to integrate WAL pages into the database file.

    Args:
        db_path: Path to the SQLite database file.
        mode: Checkpoint mode ('PASSIVE', 'FULL', 'RESTART', or 'TRUNCATE').

    Returns:
        Tuple of (busy_status, total_wal_pages, checkpointed_pages).
    """
    valid_modes = {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}
    chk_mode = mode.upper() if mode.upper() in valid_modes else "PASSIVE"

    conn = get_connection(db_path)
    try:
        cur = conn.execute(f"PRAGMA wal_checkpoint({chk_mode});")
        row = cur.fetchone()
        if row:
            busy, log_pages, checkpointed = row[0], row[1], row[2]
            logger.debug(
                "WAL checkpoint (%s): busy=%d, log_pages=%d, checkpointed=%d",
                chk_mode,
                busy,
                log_pages,
                checkpointed,
            )
            return (busy, log_pages, checkpointed)
        return (0, 0, 0)
    finally:
        conn.close()


def get_db_file_sizes(db_path: str) -> Dict[str, int]:
    """Return file sizes in bytes for database file, WAL log, and shared memory file."""
    db_file = Path(db_path)
    wal_file = Path(f"{db_path}-wal")
    shm_file = Path(f"{db_path}-shm")

    return {
        "db_bytes": db_file.stat().st_size if db_file.exists() else 0,
        "wal_bytes": wal_file.stat().st_size if wal_file.exists() else 0,
        "shm_bytes": shm_file.stat().st_size if shm_file.exists() else 0,
        "total_bytes": (
            (db_file.stat().st_size if db_file.exists() else 0)
            + (wal_file.stat().st_size if wal_file.exists() else 0)
            + (shm_file.stat().st_size if shm_file.exists() else 0)
        ),
    }
