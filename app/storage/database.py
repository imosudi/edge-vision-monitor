"""
SQLite database connection management, WAL mode configuration, and schema migration.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Generator
from app.core.logging_config import get_logger

logger = get_logger("STORAGE.DB")

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;

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
    Configures SQLite in Write-Ahead-Logging (WAL) mode for concurrent read/write.
    """
    path_obj = Path(db_path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path, timeout=10.0) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()

    logger.info("Database initialised with WAL mode at '%s'", db_path)


def get_connection(db_path: str) -> sqlite3.Connection:
    """
    Get a new configured SQLite connection.
    Enables row factory for dict-like access.
    """
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn
