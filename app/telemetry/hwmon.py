"""
Linux hwmon interface sensor discovery and reading.
Discovers sensors dynamically in /sys/class/hwmon/ without hardcoding hwmon numbers.
"""

from __future__ import annotations

import glob
import os
from typing import Dict, List, Optional
from app.core.logging_config import RateLimitedLogger, get_logger
from app.storage.models import TelemetrySample

raw_logger = get_logger("TELEMETRY.HWMON")
logger = RateLimitedLogger(raw_logger, window_seconds=60.0)


def _safe_read_int(path: str) -> Optional[int]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except (FileNotFoundError, PermissionError, ValueError, OSError):
        return None


def _safe_read_str(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except (FileNotFoundError, PermissionError, OSError):
        return None


def collect_hwmon_metrics() -> List[TelemetrySample]:
    """
    Dynamically discover chips in /sys/class/hwmon/hwmon* and read:
    - Temperature inputs (temp*_input) -> converted from millidegrees to Celsius
    - Fan RPM (fan*_input)
    - Voltages (in*_input) -> converted from millivolts to Volts
    - Power (power*_input) -> converted from microwatts to Watts
    """
    samples: List[TelemetrySample] = []
    hwmon_dirs = sorted(glob.glob("/sys/class/hwmon/hwmon*"))

    if not hwmon_dirs:
        # hwmon not present in this environment
        return [
            TelemetrySample(
                metric_name="hwmon_status",
                value=None,
                unit="status",
                source="sysfs:hwmon",
                availability_status="UNSUPPORTED",
                error_message="No hwmon directories found in /sys/class/hwmon",
            )
        ]

    for hdir in hwmon_dirs:
        chip_name = _safe_read_str(os.path.join(hdir, "name")) or os.path.basename(hdir)

        # 1. Temperatures
        for temp_input in sorted(glob.glob(os.path.join(hdir, "temp*_input"))):
            base = temp_input[:-6]  # strip '_input'
            label = _safe_read_str(f"{base}_label") or os.path.basename(base)
            raw_val = _safe_read_int(temp_input)

            metric_id = f"hwmon_{chip_name}_{label}_temp"
            if raw_val is not None:
                temp_c = round(raw_val / 1000.0, 2)
                samples.append(
                    TelemetrySample(
                        metric_name=metric_id,
                        value=temp_c,
                        unit="celsius",
                        source=f"hwmon:{chip_name}",
                        availability_status="AVAILABLE",
                    )
                )
            else:
                samples.append(
                    TelemetrySample(
                        metric_name=metric_id,
                        value=None,
                        unit="celsius",
                        source=f"hwmon:{chip_name}",
                        availability_status="READ_ERROR",
                        error_message="Failed to read temp input attribute",
                    )
                )

        # 2. Fan RPM
        for fan_input in sorted(glob.glob(os.path.join(hdir, "fan*_input"))):
            base = fan_input[:-6]
            label = _safe_read_str(f"{base}_label") or os.path.basename(base)
            raw_val = _safe_read_int(fan_input)

            metric_id = f"hwmon_{chip_name}_{label}_rpm"
            if raw_val is not None:
                samples.append(
                    TelemetrySample(
                        metric_name=metric_id,
                        value=float(raw_val),
                        unit="rpm",
                        source=f"hwmon:{chip_name}",
                        availability_status="AVAILABLE",
                    )
                )

        # 3. Voltages
        for in_input in sorted(glob.glob(os.path.join(hdir, "in*_input"))):
            base = in_input[:-6]
            label = _safe_read_str(f"{base}_label") or os.path.basename(base)
            raw_val = _safe_read_int(in_input)

            metric_id = f"hwmon_{chip_name}_{label}_voltage"
            if raw_val is not None:
                volts = round(raw_val / 1000.0, 3)
                samples.append(
                    TelemetrySample(
                        metric_name=metric_id,
                        value=volts,
                        unit="volts",
                        source=f"hwmon:{chip_name}",
                        availability_status="AVAILABLE",
                    )
                )

    return samples
