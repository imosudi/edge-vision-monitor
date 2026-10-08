"""
Linux thermal zones (/sys/class/thermal/thermal_zone*) and cooling devices collector.
"""

from __future__ import annotations

import glob
import os
from typing import List, Optional
from app.core.logging_config import RateLimitedLogger, get_logger
from app.storage.models import TelemetrySample

raw_logger = get_logger("TELEMETRY.THERMAL")
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


def collect_thermal_metrics() -> List[TelemetrySample]:
    """Collect temperature readings from all active thermal zones."""
    samples: List[TelemetrySample] = []
    zone_dirs = sorted(glob.glob("/sys/class/thermal/thermal_zone*"))

    for zdir in zone_dirs:
        zname = os.path.basename(zdir)
        ztype = _safe_read_str(os.path.join(zdir, "type")) or zname
        raw_temp = _safe_read_int(os.path.join(zdir, "temp"))

        # Clean metric identifier
        clean_type = ztype.lower().replace(" ", "_").replace("-", "_")
        metric_name = f"thermal_{clean_type}_temp"

        if raw_temp is not None:
            # Temperature is reported in millidegrees Celsius
            temp_c = round(raw_temp / 1000.0, 2)
            samples.append(
                TelemetrySample(
                    metric_name=metric_name,
                    value=temp_c,
                    unit="celsius",
                    source=f"thermal:{zname}",
                    availability_status="AVAILABLE",
                )
            )
        else:
            samples.append(
                TelemetrySample(
                    metric_name=metric_name,
                    value=None,
                    unit="celsius",
                    source=f"thermal:{zname}",
                    availability_status="READ_ERROR",
                    error_message=f"Could not read temperature from {zdir}/temp",
                )
            )

    # Cooling devices (fan speeds / states)
    cooling_dirs = sorted(glob.glob("/sys/class/thermal/cooling_device*"))
    for cdir in cooling_dirs:
        cname = os.path.basename(cdir)
        ctype = _safe_read_str(os.path.join(cdir, "type")) or cname
        cur_state = _safe_read_int(os.path.join(cdir, "cur_state"))
        max_state = _safe_read_int(os.path.join(cdir, "max_state"))

        clean_type = ctype.lower().replace(" ", "_").replace("-", "_")
        metric_name = f"cooling_{clean_type}_cur_state"

        if cur_state is not None:
            samples.append(
                TelemetrySample(
                    metric_name=metric_name,
                    value=float(cur_state),
                    unit="state",
                    source=f"cooling:{cname}",
                    availability_status="AVAILABLE",
                )
            )

    return samples
