"""
Raspberry Pi sysfs metrics, Linux /proc accounting, CPU delta calculations,
and vcgencmd throttling bitfield decoding.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple
from app.core.logging_config import RateLimitedLogger, get_logger
from app.storage.models import TelemetrySample

raw_logger = get_logger("TELEMETRY.RPI")
logger = RateLimitedLogger(raw_logger, window_seconds=60.0)


class ThrottlingDecoder:
    """Decodes Raspberry Pi vcgencmd get_throttled bitfields."""

    BIT_UNDERVOLTAGE_NOW = 1 << 0
    BIT_ARM_FREQ_CAPPED_NOW = 1 << 1
    BIT_THROTTLED_NOW = 1 << 2
    BIT_SOFT_TEMP_LIMIT_NOW = 1 << 3
    BIT_UNDERVOLTAGE_PAST = 1 << 16
    BIT_ARM_FREQ_CAPPED_PAST = 1 << 17
    BIT_THROTTLED_PAST = 1 << 18
    BIT_SOFT_TEMP_LIMIT_PAST = 1 << 19

    @classmethod
    def decode(cls, raw_val: int) -> Dict[str, Any]:
        return {
            "raw_value": hex(raw_val),
            "raw_int": raw_val,
            "undervoltage_now": bool(raw_val & cls.BIT_UNDERVOLTAGE_NOW),
            "arm_freq_capped_now": bool(raw_val & cls.BIT_ARM_FREQ_CAPPED_NOW),
            "throttled_now": bool(raw_val & cls.BIT_THROTTLED_NOW),
            "soft_temp_limit_now": bool(raw_val & cls.BIT_SOFT_TEMP_LIMIT_NOW),
            "undervoltage_occurred": bool(raw_val & cls.BIT_UNDERVOLTAGE_PAST),
            "arm_freq_capped_occurred": bool(raw_val & cls.BIT_ARM_FREQ_CAPPED_PAST),
            "throttled_occurred": bool(raw_val & cls.BIT_THROTTLED_PAST),
            "soft_temp_limit_occurred": bool(raw_val & cls.BIT_SOFT_TEMP_LIMIT_PAST),
            "is_throttled_or_undervolted": bool(raw_val & (0xF)),  # any active current flag
        }


class RaspberryPiTelemetry:
    """Stateful sampler for Raspberry Pi / Linux host metrics with delta computations."""

    def __init__(self):
        self._prev_cpu_total: Optional[int] = None
        self._prev_cpu_idle: Optional[int] = None
        self._prev_net_rx: Optional[int] = None
        self._prev_net_tx: Optional[int] = None
        self._prev_net_time: Optional[float] = None

    def read_cpu_utilisation(self) -> Optional[float]:
        """Compute CPU utilisation percentage from successive /proc/stat reads."""
        try:
            with open("/proc/stat", "r", encoding="utf-8") as f:
                line = f.readline()
            if not line.startswith("cpu "):
                return None

            fields = [int(x) for x in line.strip().split()[1:]]
            idle = fields[3] + (fields[4] if len(fields) > 4 else 0)  # idle + iowait
            total = sum(fields)

            if self._prev_cpu_total is None:
                self._prev_cpu_total = total
                self._prev_cpu_idle = idle
                return None

            delta_total = total - self._prev_cpu_total
            delta_idle = idle - (self._prev_cpu_idle or 0)

            self._prev_cpu_total = total
            self._prev_cpu_idle = idle

            if delta_total > 0:
                util = 100.0 * (1.0 - (delta_idle / delta_total))
                return round(max(0.0, min(100.0, util)), 1)
        except Exception:
            return None
        return None

    def read_memory(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Read RAM utilisation percentage, total MB, and available MB from /proc/meminfo."""
        try:
            mem_total_kb = None
            mem_avail_kb = None
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        mem_total_kb = int(line.split()[1])
                    elif line.startswith("MemAvailable:"):
                        mem_avail_kb = int(line.split()[1])
                    if mem_total_kb is not None and mem_avail_kb is not None:
                        break

            if mem_total_kb and mem_avail_kb:
                used_kb = mem_total_kb - mem_avail_kb
                pct = round((used_kb / mem_total_kb) * 100.0, 1)
                total_mb = round(mem_total_kb / 1024.0, 1)
                avail_mb = round(mem_avail_kb / 1024.0, 1)
                return pct, total_mb, avail_mb
        except Exception:
            pass
        return None, None, None

    def read_cpu_frequencies(self) -> Dict[str, float]:
        """Read per-core CPU frequency in MHz from sysfs."""
        freqs: Dict[str, float] = {}
        for path in sorted(glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq")):
            core = os.path.basename(os.path.dirname(os.path.dirname(path)))
            try:
                with open(path, "r", encoding="utf-8") as f:
                    khz = int(f.read().strip())
                    freqs[core] = round(khz / 1000.0, 1)
            except Exception:
                pass
        return freqs

    def read_cpu_base_freq(self) -> float:
        """Read maximum hardware base frequency in MHz (defaults to 2400.0 for Raspberry Pi 5)."""
        try:
            with open("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq", "r", encoding="utf-8") as f:
                return round(int(f.read().strip()) / 1000.0, 1)
        except Exception:
            return 2400.0

    def read_cpu_thermal_zone_temp(self) -> Optional[float]:
        """Read thermal zone0 temperature in Celsius."""
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r", encoding="utf-8") as f:
                return round(int(f.read().strip()) / 1000.0, 2)
        except Exception:
            return None

    def read_load_average(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Read 1m, 5m, 15m load average from /proc/loadavg."""
        try:
            with open("/proc/loadavg", "r", encoding="utf-8") as f:
                parts = f.read().strip().split()
                return float(parts[0]), float(parts[1]), float(parts[2])
        except Exception:
            return None, None, None

    def read_disk_usage(self, mount_point: str = "/") -> Tuple[Optional[float], Optional[float]]:
        """Read disk used percentage and free GB."""
        try:
            usage = shutil.disk_usage(mount_point)
            pct = round((usage.used / usage.total) * 100.0, 1)
            free_gb = round(usage.free / (1024**3), 2)
            return pct, free_gb
        except Exception:
            return None, None

    def read_actual_arm_freq_mhz(self) -> Optional[float]:
        """Read actual hardware ARM PLL clock in MHz using vcgencmd measure_clock arm."""
        try:
            res = subprocess.run(
                ["vcgencmd", "measure_clock", "arm"],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            if res.returncode == 0 and "=" in res.stdout:
                hz = int(res.stdout.strip().split("=")[1])
                return round(hz / 1_000_000.0, 1)
        except Exception:
            pass
        return None

    def read_throttled(self) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
        """Query vcgencmd get_throttled and decode bitfields."""
        try:
            res = subprocess.run(
                ["vcgencmd", "get_throttled"],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            if res.returncode == 0 and "throttled=" in res.stdout:
                val_str = res.stdout.strip().split("throttled=")[1]
                raw_int = int(val_str, 16)
                decoded = ThrottlingDecoder.decode(raw_int)
                return raw_int, decoded
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            pass
        return None, None

    def collect(self) -> List[TelemetrySample]:
        """Sample all Raspberry Pi / Linux host metrics."""
        samples: List[TelemetrySample] = []

        # 1. CPU utilisation
        cpu_pct = self.read_cpu_utilisation()
        samples.append(
            TelemetrySample(
                metric_name="cpu_utilisation",
                value=cpu_pct,
                unit="percent",
                source="proc:stat",
                availability_status="AVAILABLE" if cpu_pct is not None else "UNAVAILABLE",
            )
        )

        # 2. Memory
        mem_pct, mem_total, mem_avail = self.read_memory()
        samples.append(
            TelemetrySample(
                metric_name="memory_utilisation",
                value=mem_pct,
                unit="percent",
                source="proc:meminfo",
                availability_status="AVAILABLE" if mem_pct is not None else "UNAVAILABLE",
            )
        )
        if mem_avail is not None:
            samples.append(
                TelemetrySample(
                    metric_name="memory_available_mb",
                    value=mem_avail,
                    unit="megabytes",
                    source="proc:meminfo",
                    availability_status="AVAILABLE",
                )
            )

        # 3. Hardware Throttling State & Actual Hardware ARM Clock
        raw_throttled, decoded_throttled = self.read_throttled()
        cpu_temp = self.read_cpu_thermal_zone_temp()
        arm_hw_mhz = self.read_actual_arm_freq_mhz()

        arm_freq_capped = False
        throttled_now = False
        soft_temp_limit = False
        undervoltage_now = False
        arm_freq_capped_past = False

        if raw_throttled is not None and decoded_throttled is not None:
            arm_freq_capped = decoded_throttled["arm_freq_capped_now"]
            throttled_now = decoded_throttled["throttled_now"]
            soft_temp_limit = decoded_throttled["soft_temp_limit_now"]
            undervoltage_now = decoded_throttled["undervoltage_now"]
            arm_freq_capped_past = decoded_throttled["arm_freq_capped_occurred"]

            samples.append(
                TelemetrySample(
                    metric_name="rpi_throttled_raw",
                    value=float(raw_throttled),
                    unit="flags",
                    source="vcgencmd",
                    availability_status="AVAILABLE",
                )
            )
            samples.append(
                TelemetrySample(
                    metric_name="rpi_is_throttled",
                    value=1.0 if decoded_throttled["is_throttled_or_undervolted"] else 0.0,
                    unit="boolean",
                    source="vcgencmd",
                    availability_status="AVAILABLE",
                )
            )
            samples.append(
                TelemetrySample(
                    metric_name="rpi_undervoltage_now",
                    value=1.0 if undervoltage_now else 0.0,
                    unit="boolean",
                    source="vcgencmd",
                    availability_status="AVAILABLE",
                )
            )
            samples.append(
                TelemetrySample(
                    metric_name="rpi_arm_freq_capped_now",
                    value=1.0 if arm_freq_capped else 0.0,
                    unit="boolean",
                    source="vcgencmd",
                    availability_status="AVAILABLE",
                )
            )
            samples.append(
                TelemetrySample(
                    metric_name="rpi_throttled_now",
                    value=1.0 if throttled_now else 0.0,
                    unit="boolean",
                    source="vcgencmd",
                    availability_status="AVAILABLE",
                )
            )
            samples.append(
                TelemetrySample(
                    metric_name="rpi_soft_temp_limit_now",
                    value=1.0 if soft_temp_limit else 0.0,
                    unit="boolean",
                    source="vcgencmd",
                    availability_status="AVAILABLE",
                )
            )
            samples.append(
                TelemetrySample(
                    metric_name="rpi_arm_freq_capped_past",
                    value=1.0 if arm_freq_capped_past else 0.0,
                    unit="boolean",
                    source="vcgencmd",
                    availability_status="AVAILABLE",
                )
            )
        else:
            samples.append(
                TelemetrySample(
                    metric_name="rpi_throttled_raw",
                    value=None,
                    unit="flags",
                    source="vcgencmd",
                    availability_status="UNSUPPORTED",
                    error_message="vcgencmd not present or unsupported on host",
                )
            )

        if arm_hw_mhz is not None:
            samples.append(
                TelemetrySample(
                    metric_name="cpu_freq_arm_actual_mhz",
                    value=arm_hw_mhz,
                    unit="megahertz",
                    source="vcgencmd:measure_clock",
                    availability_status="AVAILABLE",
                )
            )

        # 4. CPU Frequencies
        freqs = self.read_cpu_frequencies()
        base_freq = self.read_cpu_base_freq()

        # If hardware ARM frequency capping or throttling is active, or actual clock is lower than governor target:
        if arm_hw_mhz is not None and (arm_freq_capped or throttled_now or soft_temp_limit or arm_hw_mhz < 2380.0):
            cur_freq = arm_hw_mhz
            for core in freqs:
                if freqs[core] > arm_hw_mhz:
                    freqs[core] = arm_hw_mhz
        else:
            cur_freq = freqs.get("cpu0", arm_hw_mhz or base_freq) if freqs else (arm_hw_mhz or base_freq)

        for core, mhz in freqs.items():
            samples.append(
                TelemetrySample(
                    metric_name=f"cpu_freq_{core}_mhz",
                    value=mhz,
                    unit="megahertz",
                    source="vcgencmd:measure_clock" if (arm_hw_mhz is not None and (arm_freq_capped or throttled_now)) else f"sysfs:{core}",
                    availability_status="AVAILABLE",
                )
            )

        samples.append(
            TelemetrySample(
                metric_name="cpu_freq_base_mhz",
                value=base_freq,
                unit="megahertz",
                source="sysfs:cpu0/cpuinfo_max_freq",
                availability_status="AVAILABLE",
            )
        )

        samples.append(
            TelemetrySample(
                metric_name="cpu_freq_cur_mhz",
                value=cur_freq,
                unit="megahertz",
                source="vcgencmd:measure_clock" if arm_hw_mhz is not None else "sysfs:cpu0/scaling_cur_freq",
                availability_status="AVAILABLE",
            )
        )

        is_full_base = cur_freq >= (base_freq - 15.0)
        samples.append(
            TelemetrySample(
                metric_name="cpu_is_full_base_freq",
                value=1.0 if is_full_base else 0.0,
                unit="boolean",
                source="hardware:cpufreq",
                availability_status="AVAILABLE",
            )
        )

        # 4. Load Average
        load1, load5, load15 = self.read_load_average()
        if load1 is not None:
            samples.append(
                TelemetrySample(
                    metric_name="load_average_1m",
                    value=load1,
                    unit="load",
                    source="proc:loadavg",
                    availability_status="AVAILABLE",
                )
            )

        # 5. Disk Usage
        disk_pct, disk_free = self.read_disk_usage()
        if disk_pct is not None:
            samples.append(
                TelemetrySample(
                    metric_name="disk_utilisation",
                    value=disk_pct,
                    unit="percent",
                    source="shutil:disk_usage",
                    availability_status="AVAILABLE",
                )
            )

        # 6. Thermal Throttling Drop determination:
        # Detects when operating at/near full base frequency (2.4 GHz) and thermal throttling forces clock down
        is_thermal_throttling = False
        throttle_drop_mhz = 0.0

        if (arm_freq_capped or soft_temp_limit or throttled_now) and (cur_freq < (base_freq - 15.0)):
            is_thermal_throttling = True
            throttle_drop_mhz = round(base_freq - cur_freq, 1)
        elif (cpu_temp is not None and cpu_temp >= 80.0) and (cur_freq < (base_freq - 30.0)):
            # Fallback in case of elevated thermal zone threshold breach
            is_thermal_throttling = True
            throttle_drop_mhz = round(base_freq - cur_freq, 1)
        elif arm_freq_capped and (cur_freq < (base_freq - 5.0)):
            is_thermal_throttling = True
            throttle_drop_mhz = round(base_freq - cur_freq, 1)

        samples.append(
            TelemetrySample(
                metric_name="cpu_thermal_throttle_active",
                value=1.0 if is_thermal_throttling else 0.0,
                unit="boolean",
                source="hardware:thermal_throttle",
                availability_status="AVAILABLE",
            )
        )
        samples.append(
            TelemetrySample(
                metric_name="cpu_freq_throttle_drop_mhz",
                value=throttle_drop_mhz,
                unit="megahertz",
                source="hardware:thermal_throttle",
                availability_status="AVAILABLE",
            )
        )

        return samples
