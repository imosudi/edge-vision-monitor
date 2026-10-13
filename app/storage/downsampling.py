"""
Time-series query downsampling algorithms for Edge Vision Monitor.
Provides Largest-Triangle-Three-Buckets (LTTB), temporal bucket aggregation,
and strided subsampling for responsive dashboard charting.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple


def _parse_timestamp_to_epoch(ts: Any) -> float:
    """Convert ISO-8601 string or numeric timestamp to epoch seconds."""
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            # Handle ISO timestamp strings
            clean_ts = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_ts)
            return dt.timestamp()
        except Exception:
            try:
                return float(ts)
            except ValueError:
                return 0.0
    return 0.0


def downsample_lttb(
    data: List[Dict[str, Any]],
    target_points: int,
    x_key: str = "timestamp_utc",
    y_key: str = "value",
) -> List[Dict[str, Any]]:
    """
    Largest-Triangle-Three-Buckets (LTTB) downsampling algorithm.

    Preserves visual peaks, troughs, and waveform geometry when reducing
    high-frequency time-series datasets to a target display resolution.

    Args:
        data: Chronologically ordered list of metric dictionaries.
        target_points: Desired number of points in downsampled output.
        x_key: Dictionary key for timestamp (ISO string or float epoch).
        y_key: Dictionary key for numeric measurement value.

    Returns:
        Downsampled list of records preserving extreme points and trends.
    """
    n_data = len(data)
    if target_points >= n_data or target_points < 3:
        return list(data)

    # Extract coordinates as (epoch_x, value_y, original_dict)
    points: List[Tuple[float, float, Dict[str, Any]]] = []
    for idx, item in enumerate(data):
        raw_val = item.get(y_key)
        if raw_val is None or not isinstance(raw_val, (int, float)) or math.isnan(raw_val):
            continue
        epoch_x = _parse_timestamp_to_epoch(item.get(x_key, idx))
        points.append((epoch_x, float(raw_val), item))

    n_valid = len(points)
    if target_points >= n_valid or target_points < 3:
        return [p[2] for p in points]

    sampled: List[Dict[str, Any]] = []

    # First point is always selected
    sampled.append(points[0][2])
    a_x, a_y = points[0][0], points[0][1]

    bucket_size = (n_valid - 2) / (target_points - 2)

    for i in range(target_points - 2):
        # Calculate current bucket range
        curr_bucket_start = int(math.floor((i + 0) * bucket_size)) + 1
        curr_bucket_end = int(math.floor((i + 1) * bucket_size)) + 1
        curr_bucket_end = min(curr_bucket_end, n_valid - 1)

        # Calculate next bucket range for center-of-mass anchor
        next_bucket_start = int(math.floor((i + 1) * bucket_size)) + 1
        next_bucket_end = int(math.floor((i + 2) * bucket_size)) + 1
        next_bucket_end = min(next_bucket_end, n_valid)

        # Average point of next bucket (c)
        next_count = max(1, next_bucket_end - next_bucket_start)
        avg_next_x = 0.0
        avg_next_y = 0.0
        for k in range(next_bucket_start, next_bucket_end):
            avg_next_x += points[k][0]
            avg_next_y += points[k][1]
        avg_next_x /= next_count
        avg_next_y /= next_count

        # Find point in current bucket that maximises triangle area (a, b, c)
        max_area = -1.0
        best_point = points[curr_bucket_start]

        for k in range(curr_bucket_start, curr_bucket_end):
            b_x = points[k][0]
            b_y = points[k][1]
            # Area = 0.5 * |(a_x - avg_next_x)*(b_y - a_y) - (a_x - b_x)*(avg_next_y - a_y)|
            area = abs(
                (a_x - avg_next_x) * (b_y - a_y) - (a_x - b_x) * (avg_next_y - a_y)
            ) * 0.5

            if area > max_area:
                max_area = area
                best_point = points[k]

        sampled.append(best_point[2])
        a_x, a_y = best_point[0], best_point[1]

    # Last point is always selected
    sampled.append(points[-1][2])
    return sampled


def downsample_bucket_aggregation(
    data: List[Dict[str, Any]],
    target_points: Optional[int] = None,
    bucket_seconds: Optional[float] = None,
    x_key: str = "timestamp_utc",
    y_key: str = "value",
) -> List[Dict[str, Any]]:
    """
    Time-window bucket aggregation downsampling.

    Calculates mean, minimum, maximum, and sample count across equal time windows.

    Args:
        data: Chronologically ordered list of metric dictionaries.
        target_points: Desired number of bucket windows across range.
        bucket_seconds: Explicit duration in seconds per bucket window.
        x_key: Dictionary key for timestamp.
        y_key: Dictionary key for numeric measurement value.

    Returns:
        List of aggregated bucket summary records.
    """
    if not data:
        return []

    # Extract valid points
    valid_records: List[Tuple[float, float, Dict[str, Any]]] = []
    for idx, item in enumerate(data):
        val = item.get(y_key)
        if val is None or not isinstance(val, (int, float)) or math.isnan(val):
            continue
        epoch_x = _parse_timestamp_to_epoch(item.get(x_key, idx))
        valid_records.append((epoch_x, float(val), item))

    if not valid_records:
        return []

    min_time = valid_records[0][0]
    max_time = valid_records[-1][0]
    duration = max_time - min_time

    if bucket_seconds is not None and bucket_seconds > 0:
        step = bucket_seconds
        max_buckets = None
    elif target_points is not None and target_points > 1 and duration > 0:
        step = duration / target_points
        max_buckets = target_points
    else:
        # Default fallback: up to 100 points
        step = max(0.1, duration / 100.0) if duration > 0 else 1.0
        max_buckets = 100

    buckets: Dict[int, List[Tuple[float, float, Dict[str, Any]]]] = {}
    for pt in valid_records:
        if step > 0:
            raw_idx = int((pt[0] - min_time) / step)
            bucket_idx = min(raw_idx, max_buckets - 1) if max_buckets else raw_idx
        else:
            bucket_idx = 0

        if bucket_idx not in buckets:
            buckets[bucket_idx] = []
        buckets[bucket_idx].append(pt)

    aggregated: List[Dict[str, Any]] = []
    for b_idx in sorted(buckets.keys()):
        pts = buckets[b_idx]
        values = [p[1] for p in pts]
        mean_val = round(sum(values) / len(values), 3)
        min_val = round(min(values), 3)
        max_val = round(max(values), 3)

        # Baseline record properties from first entry in bucket
        rep = dict(pts[0][2])
        rep[y_key] = mean_val
        rep["min_value"] = min_val
        rep["max_value"] = max_val
        rep["sample_count"] = len(values)
        rep["timestamp_utc"] = pts[0][2].get(x_key)
        aggregated.append(rep)

    return aggregated


def downsample_stride(data: List[Dict[str, Any]], stride: int = 1) -> List[Dict[str, Any]]:
    """Uniform stride subsampling: returns every Nth record."""
    if stride <= 1 or not data:
        return list(data)
    return data[::stride]
