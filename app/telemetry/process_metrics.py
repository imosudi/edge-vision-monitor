"""
Application process metrics and Linux cgroup container resource monitoring.
"""

from __future__ import annotations

import os
import threading
import time
from typing import List, Optional, Tuple
from app.storage.models import TelemetrySample


class ProcessMetricsSampler:
    """Samples current process resource consumption (RSS memory, threads, CPU time)."""

    def __init__(self):
        self._pid = os.getpid()
        self._prev_proc_time: Optional[float] = None
        self._prev_monotonic: Optional[float] = None

    def read_process_stats(self) -> Tuple[Optional[float], Optional[float], int]:
        """
        Returns:
            cpu_percent: Estimated process CPU usage %.
            rss_mb: Resident Set Size in Megabytes.
            thread_count: Active OS thread count for this process.
        """
        rss_mb: Optional[float] = None
        cpu_pct: Optional[float] = None
        thread_count = threading.active_count()

        # Read /proc/[pid]/stat for CPU time and threads
        try:
            with open(f"/proc/{self._pid}/stat", "r", encoding="utf-8") as f:
                parts = f.read().split()
                utime = int(parts[13])
                stime = int(parts[14])
                threads = int(parts[19])
                thread_count = threads
                proc_time = (utime + stime) / 100.0  # approximate clock ticks to seconds

            now = time.monotonic()
            if self._prev_proc_time is not None and self._prev_monotonic is not None:
                delta_time = now - self._prev_monotonic
                delta_proc = proc_time - self._prev_proc_time
                if delta_time > 0:
                    cpu_pct = round((delta_proc / delta_time) * 100.0, 1)

            self._prev_proc_time = proc_time
            self._prev_monotonic = now
        except Exception:
            pass

        # Read /proc/[pid]/status for VmRSS
        try:
            with open(f"/proc/{self._pid}/status", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        rss_kb = int(line.split()[1])
                        rss_mb = round(rss_kb / 1024.0, 2)
                        break
        except Exception:
            pass

        return cpu_pct, rss_mb, thread_count

    def read_cgroup_memory_mb(self) -> Optional[float]:
        """Read cgroup v2 memory.current if running in container."""
        cgroup_mem_path = "/sys/fs/cgroup/memory.current"
        if os.path.isfile(cgroup_mem_path):
            try:
                with open(cgroup_mem_path, "r", encoding="utf-8") as f:
                    bytes_val = int(f.read().strip())
                    return round(bytes_val / (1024 * 1024), 2)
            except Exception:
                pass
        return None

    def collect(self) -> List[TelemetrySample]:
        samples: List[TelemetrySample] = []
        cpu_pct, rss_mb, threads = self.read_process_stats()

        if cpu_pct is not None:
            samples.append(
                TelemetrySample(
                    metric_name="process_cpu_percent",
                    value=cpu_pct,
                    unit="percent",
                    source="proc:status",
                    availability_status="AVAILABLE",
                )
            )

        if rss_mb is not None:
            samples.append(
                TelemetrySample(
                    metric_name="process_memory_rss_mb",
                    value=rss_mb,
                    unit="megabytes",
                    source="proc:status",
                    availability_status="AVAILABLE",
                )
            )

        samples.append(
            TelemetrySample(
                metric_name="process_threads_count",
                value=float(threads),
                unit="count",
                source="proc:stat",
                availability_status="AVAILABLE",
            )
        )

        cgroup_mem = self.read_cgroup_memory_mb()
        if cgroup_mem is not None:
            samples.append(
                TelemetrySample(
                    metric_name="container_cgroup_memory_mb",
                    value=cgroup_mem,
                    unit="megabytes",
                    source="cgroup:memory.current",
                    availability_status="AVAILABLE",
                )
            )

        return samples
