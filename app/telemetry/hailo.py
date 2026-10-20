"""
HailoRT accelerator telemetry, PCIe link inspection, and NPU device health.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Dict, List, Optional
from app.core.logging_config import RateLimitedLogger, get_logger
from app.storage.models import TelemetrySample

raw_logger = get_logger("TELEMETRY.HAILO")
logger = RateLimitedLogger(raw_logger, window_seconds=60.0)


def collect_hailo_telemetry() -> List[TelemetrySample]:
    """
    Collect verifiable Hailo-8L accelerator metrics without fabricating values.
    Uses capability detection against /dev/hailo0 and installed HailoRT tools.
    """
    samples: List[TelemetrySample] = []
    device_exists = os.path.exists("/dev/hailo0")

    # 1. Device Presence
    samples.append(
        TelemetrySample(
            metric_name="hailo_device_present",
            value=1.0 if device_exists else 0.0,
            unit="boolean",
            source="dev:/dev/hailo0",
            availability_status="AVAILABLE",
        )
    )

    if not device_exists:
        # Report device unavailable for dependent metrics
        samples.append(
            TelemetrySample(
                metric_name="hailo_temperature_c",
                value=None,
                unit="celsius",
                source="hailort",
                availability_status="UNAVAILABLE",
                error_message="Hailo device node '/dev/hailo0' not found",
            )
        )
        samples.append(
            TelemetrySample(
                metric_name="hailo_power_watts",
                value=None,
                unit="watts",
                source="hailort",
                availability_status="UNAVAILABLE",
                error_message="Hailo device node '/dev/hailo0' not found",
            )
        )
        return samples

    # 2. Query hailo tool if available (e.g., hailortcli fw-control or hailo-pci driver sysfs)
    # Check PCIe link info in sysfs
    pcie_dirs = [
        "/sys/bus/pci/drivers/hailo_pci",
        "/sys/bus/pci/drivers/hailo",
        "/sys/class/hailo_chardev",
        "/sys/class/hailo",
        "/sys/module/hailo_pci",
    ]
    driver_loaded = any(os.path.isdir(d) for d in pcie_dirs)
    samples.append(
        TelemetrySample(
            metric_name="hailo_driver_loaded",
            value=1.0 if driver_loaded else 0.0,
            unit="boolean",
            source="sysfs:pci",
            availability_status="AVAILABLE",
        )
    )

    # 3. Query Hailo-8L on-die chip temperature via HailoRT control interface
    hailo_temp_c: Optional[float] = None
    hailo_power_w: Optional[float] = None

    try:
        from hailo_platform.pyhailort import pyhailort as _ph  # type: ignore
        _devs = _ph.Device.scan()
        if _devs:
            _d = _ph.Device(_devs[0])
            _temp_info = _d.control.get_chip_temperature()
            hailo_temp_c = round(float(_temp_info.ts0_temperature), 1)
    except Exception:
        pass

    try:
        # Try hailortcli measure if present
        res = subprocess.run(
            ["hailortcli", "measure", "--power", "--time", "1"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if "Power" in line and "W" in line:
                    parts = line.split()
                    for p in parts:
                        try:
                            hailo_power_w = float(p.replace("W", ""))
                            break
                        except ValueError:
                            pass
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass

    samples.append(
        TelemetrySample(
            metric_name="hailo_temperature_c",
            value=hailo_temp_c,
            unit="celsius",
            source="hailort:device_control",
            availability_status="AVAILABLE" if hailo_temp_c is not None else "UNSUPPORTED",
            error_message=None if hailo_temp_c is not None else "Hailo on-die temperature interface unavailable",
        )
    )

    samples.append(
        TelemetrySample(
            metric_name="hailo_power_watts",
            value=hailo_power_w,
            unit="watts",
            source="hailort",
            availability_status="AVAILABLE" if hailo_power_w is not None else "UNSUPPORTED",
            error_message=None if hailo_power_w is not None else "Hardware power measurement unsupported or sensor rail absent",
        )
    )

    # 4. Instantaneous NPU Compute Utilization from HailoRT monitor profiler
    hailo_util: Optional[float] = None
    try:
        import glob
        for util_file in glob.glob("/tmp/nnc_utilization/*"):
            try:
                with open(util_file, "r", encoding="utf-8") as fp:
                    content = fp.read().strip()
                    if content:
                        hailo_util = round(float(content), 1)
                        break
            except Exception:
                pass
    except Exception:
        pass

    samples.append(
        TelemetrySample(
            metric_name="hailo_utilization_percent",
            value=hailo_util,
            unit="percent",
            source="hailort:profiler",
            availability_status="AVAILABLE" if hailo_util is not None else "UNSUPPORTED",
            error_message=None if hailo_util is not None else "HailoRT monitor profiler inactive or /tmp/nnc_utilization absent",
        )
    )

    return samples

