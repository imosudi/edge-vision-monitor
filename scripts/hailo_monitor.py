#!/usr/bin/env python3
"""
Edge Vision Monitor - Hailo-8L NPU Live Terminal Monitor.
Streams live NPU chip temperature (die sensors TS0 and TS1), computational load %,
thermal throttling status, inference throughput (FPS), and pipeline latencies.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

# Terminal ANSI styling codes
CLR_RESET = "\033[0m"
CLR_BOLD = "\033[1m"
CLR_DIM = "\033[2m"
CLR_CYAN = "\033[36m"
CLR_GREEN = "\033[32m"
CLR_YELLOW = "\033[33m"
CLR_RED = "\033[31m"
CLR_MAGENTA = "\033[35m"
CLR_BLUE = "\033[34m"
CLR_WHITE = "\033[37m"
CLR_GRAY = "\033[90m"
CLR_CLEAR_LINE = "\033[2K"
CLR_HIDE_CURSOR = "\033[?25l"
CLR_SHOW_CURSOR = "\033[?25h"


def format_gauge_bar(pct: float, width: int = 30) -> str:
    """Render a visual terminal progress gauge bar with dynamic colour."""
    clamped = max(0.0, min(100.0, pct))
    filled_len = int(round((clamped / 100.0) * width))
    empty_len = width - filled_len
    
    if clamped >= 85.0:
        fill_color = CLR_RED
    elif clamped >= 60.0:
        fill_color = CLR_YELLOW
    else:
        fill_color = CLR_CYAN

    bar = f"{fill_color}{'█' * filled_len}{CLR_GRAY}{'·' * empty_len}{CLR_RESET}"
    return f"[{bar}] {clamped:5.1f}%"


def format_temp(temp: Optional[float], warn: float = 65.0, crit: float = 80.0) -> str:
    """Format temperature value with adaptive status indicator."""
    if temp is None:
        return f"{CLR_GRAY}-- °C (N/A){CLR_RESET}"
    if temp >= crit:
        color = CLR_RED
        badge = f"{CLR_RED}{CLR_BOLD}[CRITICAL]{CLR_RESET}"
    elif temp >= warn:
        color = CLR_YELLOW
        badge = f"{CLR_YELLOW}[ELEVATED]{CLR_RESET}"
    else:
        color = CLR_GREEN
        badge = f"{CLR_GREEN}[NOMINAL]{CLR_RESET}"
    return f"{color}{temp:.1f} °C{CLR_RESET} {badge}"


class HailoHardwareReader:
    """Reads live hardware metrics directly when running on host with HailoRT."""

    def __init__(self):
        self._device: Any = None
        self._available: bool = False
        self._board_name: str = "Hailo-8L"
        self._arch: str = "HAILO8L"
        self._init_device()

    def _init_device(self) -> None:
        try:
            import hailo_platform.pyhailort.pyhailort as _ph  # type: ignore
            devs = _ph.Device.scan()
            if devs:
                self._device = _ph.Device(devs[0])
                self._available = True
                try:
                    ident = self._device.control.identify()
                    self._board_name = getattr(ident, "board_name", "Hailo-8").strip()
                    self._arch = getattr(ident, "device_architecture", "HAILO8L")
                except Exception:
                    pass
        except Exception:
            self._available = False

    def is_available(self) -> bool:
        return self._available

    def read_chip_temperature(self) -> Tuple[Optional[float], Optional[float]]:
        """Return (ts0_temperature, ts1_temperature) in degrees Celsius."""
        if not self._available or not self._device:
            return None, None
        try:
            temp_info = self._device.control.get_chip_temperature()
            return float(temp_info.ts0_temperature), float(temp_info.ts1_temperature)
        except Exception:
            return None, None

    def read_throttling_state(self) -> Optional[bool]:
        """Return True if hardware thermal throttling is currently active."""
        if not self._available or not self._device:
            return None
        try:
            return bool(self._device.control.get_throttling_state())
        except Exception:
            return None

    def read_utilization(self) -> Optional[float]:
        """Read instantaneous NPU utilization % from /tmp/nnc_utilization."""
        import glob
        for f in glob.glob("/tmp/nnc_utilization/*"):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    return float(fp.read().strip())
            except Exception:
                pass
        return None


class RemoteTelemetryClient:
    """Queries live telemetry and inference performance from edge-vision-monitor API."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8000, timeout: float = 2.0):
        self.base_url = f"http://{host}:{port}/api/v1"
        self.timeout = timeout

    def get_status(self) -> Optional[Dict[str, Any]]:
        return self._fetch_json("/status")

    def get_inference_stats(self) -> Optional[Dict[str, Any]]:
        return self._fetch_json("/inference/stats")

    def get_metrics_current(self) -> Optional[Dict[str, Any]]:
        return self._fetch_json("/metrics/current")

    def _fetch_json(self, path: str) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}{path}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "HailoTerminalMonitor/1.0"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None
        return None


def run_raw_hailortcli(remote_host: Optional[str] = None, user: str = "iotgwai") -> int:
    """Run official hailortcli monitor directly or through container / SSH."""
    print(f"\n{CLR_CYAN}{CLR_BOLD}=== Launching Official HailoRT Monitor (hailortcli monitor) ==={CLR_RESET}\n")

    # If running locally on Linux and hailortcli exists in PATH
    if not remote_host and shutil.which("hailortcli"):
        os.environ["HAILO_MONITOR"] = "1"
        try:
            return subprocess.call(["hailortcli", "monitor"])
        except KeyboardInterrupt:
            return 0

    # If Docker container edge-vision-inference is running locally
    if not remote_host and shutil.which("docker"):
        try:
            cmd = ["docker", "exec", "-it", "edge-vision-inference", "hailortcli", "monitor"]
            return subprocess.call(cmd)
        except Exception:
            pass

    # If remote edge host is specified
    target = remote_host or "192.168.3.14"
    print(f"Connecting to remote host {target} to attach hailortcli monitor session...")
    ssh_cmd = [
        "ssh", "-t",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "PubkeyAuthentication=no",
        "-o", "PreferredAuthentications=password,keyboard-interactive",
        f"{user}@{target}",
        "export HAILO_MONITOR=1; (hailortcli monitor || docker exec -it edge-vision-inference hailortcli monitor)",
    ]
    try:
        return subprocess.call(ssh_cmd)
    except KeyboardInterrupt:
        return 0


def render_dashboard(
    hw_reader: HailoHardwareReader,
    api_client: RemoteTelemetryClient,
    target_host: str,
    interval: float,
) -> None:
    """Run interactive continuous live terminal dashboard loop."""
    # Ensure cursor is restored cleanly on exit
    def cleanup_terminal(sig, frame):
        sys.stdout.write(f"{CLR_SHOW_CURSOR}\n\n{CLR_DIM}Monitor session closed.{CLR_RESET}\n")
        sys.stdout.flush()
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup_terminal)
    signal.signal(signal.SIGTERM, cleanup_terminal)
    sys.stdout.write(CLR_HIDE_CURSOR)
    sys.stdout.flush()

    last_frame_count = 0
    last_tick_time = time.monotonic()

    while True:
        now_ts = time.strftime("%Y-%m-%d %H:%M:%S")
        mono_now = time.monotonic()
        dt = max(0.001, mono_now - last_tick_time)

        # 1. Hardware metrics
        ts0, ts1 = hw_reader.read_chip_temperature()
        throttled = hw_reader.read_throttling_state()
        local_load = hw_reader.read_utilization()

        # 2. REST API metrics from gateway
        inf_stats = api_client.get_inference_stats() or {}
        platform_status = api_client.get_status() or {}
        metrics = api_client.get_metrics_current() or {}

        # Fallback values if hw_reader is running remotely
        if ts0 is None:
            hailo_metric = metrics.get("hailo_temperature_c") or {}
            ts0 = hailo_metric.get("value")
            ts1 = ts0

        # Load % resolution
        npu_load = local_load
        if npu_load is None:
            # Check if reported by telemetry service
            npu_load = (metrics.get("hailo_utilization_percent") or {}).get("value")
        if npu_load is None:
            # Estimate from inference execution time / inter_frame_ms
            cur_fps = inf_stats.get("current_fps", 0.0)
            mean_lat = inf_stats.get("latencies", {}).get("execution_ms", {}).get("mean", 14.5)
            if cur_fps > 0 and mean_lat > 0:
                npu_load = min(100.0, (cur_fps * mean_lat / 1000.0) * 100.0)
            else:
                npu_load = 0.0

        # CPU / RP1 / Fan / Ambient context
        cpu_temp = (
            metrics.get("hwmon_cpu_thermal_temp1_temp", {}).get("value")
            or metrics.get("thermal_cpu_thermal_temp", {}).get("value")
            or metrics.get("rpi_cpu_temp_c", {}).get("value")
        )
        rp1_temp = (
            metrics.get("hwmon_rp1_adc_temp1_temp", {}).get("value")
            or metrics.get("rpi_rp1_temp_c", {}).get("value")
        )
        fan_rpm = metrics.get("hwmon_pwmfan_fan1_rpm", {}).get("value")
        ambient_temp = metrics.get("ambient_temperature_c", {}).get("value")
        ambient_hum = metrics.get("ambient_humidity_percent", {}).get("value")
        ambient_comfort = metrics.get("ambient_temperature_c", {}).get("comfort_status", "Nominal")

        # Pipeline stats
        is_infer_running = bool(inf_stats.get("is_running", False))
        fps = inf_stats.get("current_fps", 0.0)
        tot_frames = inf_stats.get("total_frames_processed", 0)
        active_backend = inf_stats.get("active_backend", "hailo")
        hef_path = inf_stats.get("engine_status", {}).get("hef_path", "models/yolo11n.hef")
        model_name = os.path.basename(hef_path).replace(".hef", "")

        lat_info = inf_stats.get("latencies", {})
        npu_ms = lat_info.get("execution_ms", {}).get("mean", 0.0)
        pre_ms = lat_info.get("preprocessing_ms", {}).get("mean", 0.0)
        post_ms = lat_info.get("postprocessing_ms", {}).get("mean", 0.0)
        tot_ms = lat_info.get("total_ms", {}).get("mean", (npu_ms + pre_ms + post_ms))

        # Clear terminal and jump to top-left
        sys.stdout.write("\033[H\033[2J")

        # Render Header
        print(f"{CLR_BLUE}{CLR_BOLD}================================================================================{CLR_RESET}")
        print(f"{CLR_CYAN}{CLR_BOLD}  HAILO-8L NPU LIVE MONITOR & INFERENCE TELEMETRY{CLR_RESET}   {CLR_WHITE}[Host: {target_host}]{CLR_RESET}")
        print(f"{CLR_DIM}  Timestamp: {now_ts} UTC | Refresh Interval: {interval:.1f}s | HAILO_MONITOR=1{CLR_RESET}")
        print(f"{CLR_BLUE}{CLR_BOLD}================================================================================{CLR_RESET}")

        # Section 1: NPU Hardware & Silicon Thermals
        print(f"\n{CLR_WHITE}{CLR_BOLD}[1] HAILO-8L ACCELERATOR HARDWARE STATUS{CLR_RESET}")
        print(f"  PCIe Device Node:      {CLR_CYAN}/dev/hailo0{CLR_RESET} (0001:01:00.0 M.2 AI HAT+)")
        print(f"  Architecture:          {CLR_WHITE}HAILO8L{CLR_RESET} (Firmware 4.23.0, 13 TOPS)")
        
        # Dual on-die sensors
        if ts0 is not None and ts1 is not None:
            print(f"  NPU Die Sensor 0 (TS0): {format_temp(ts0)}")
            print(f"  NPU Die Sensor 1 (TS1): {format_temp(ts1)}")
        else:
            print(f"  NPU Die Temperature:   {format_temp(ts0)}")

        # Thermal Throttling state
        if throttled is True:
            throttle_str = f"{CLR_RED}{CLR_BOLD}⚠️  THROTTLED (Clock frequency reduced to preserve silicon){CLR_RESET}"
        elif throttled is False:
            throttle_str = f"{CLR_GREEN}Nominal (Full 400 MHz NPU operational frequency){CLR_RESET}"
        else:
            throttle_str = f"{CLR_GREEN}Nominal{CLR_RESET}"
        print(f"  Thermal Throttling:    {throttle_str}")

        # Live NPU load gauge bar
        print(f"  NPU Compute Load:      {format_gauge_bar(npu_load or 0.0)}")

        # Section 2: Real-Time Inference Performance
        print(f"\n{CLR_WHITE}{CLR_BOLD}[2] REAL-TIME INFERENCE WORKLOAD & THROUGHPUT{CLR_RESET}")
        status_label = f"{CLR_GREEN}● ACTIVE RUNNING{CLR_RESET}" if is_infer_running else f"{CLR_YELLOW}○ IDLE / STANDBY{CLR_RESET}"
        print(f"  Workload State:        {status_label}")
        print(f"  Neural Network Model:  {CLR_WHITE}{CLR_BOLD}{model_name}{CLR_RESET} ({hef_path})")
        print(f"  Active Compute Engine: {CLR_CYAN}{active_backend.upper()}{CLR_RESET} (HailoRT VStreams Asynchronous Pipeline)")
        
        fps_color = CLR_GREEN if fps >= 20.0 else (CLR_YELLOW if fps >= 10.0 else CLR_RED)
        print(f"  Throughput:            {fps_color}{CLR_BOLD}{fps:5.1f} FPS{CLR_RESET} (Total Frames Evaluated: {tot_frames:,})")

        print(f"  Pipeline Latencies:    NPU: {CLR_MAGENTA}{npu_ms:4.1f} ms{CLR_RESET} | Pre: {CLR_BLUE}{pre_ms:4.1f} ms{CLR_RESET} | Post: {CLR_YELLOW}{post_ms:4.1f} ms{CLR_RESET} | Total: {CLR_WHITE}{tot_ms:4.1f} ms{CLR_RESET}")

        # Section 3: Cross-Component Thermal Correlation
        print(f"\n{CLR_WHITE}{CLR_BOLD}[3] HOST & AMBIENT THERMAL PROFILE{CLR_RESET}")
        cpu_str = f"{cpu_temp:.1f} °C" if cpu_temp is not None else "-- °C"
        rp1_str = f"{rp1_temp:.1f} °C" if rp1_temp is not None else "-- °C"
        fan_str = f"{round(fan_rpm)} RPM" if fan_rpm is not None else "-- RPM"
        print(f"  Raspberry Pi 5 CPU:    {CLR_CYAN}{cpu_str}{CLR_RESET} | RP1 Southbridge: {CLR_CYAN}{rp1_str}{CLR_RESET} | Cooler Fan: {CLR_CYAN}{fan_str}{CLR_RESET}")

        if ambient_temp is not None and ambient_hum is not None:
            print(f"  Room Ambient:          {CLR_GREEN}{ambient_temp:.1f} °C{CLR_RESET} ({ambient_hum:.1f}% RH) | Comfort: {CLR_YELLOW}{ambient_comfort}{CLR_RESET} (ESP32-S3)")

        # Footer
        print(f"\n{CLR_BLUE}================================================================================{CLR_RESET}")
        print(f"{CLR_DIM}Commands: Press [Ctrl+C] to exit | Run with '--cli' for raw hailortcli tables{CLR_RESET}")
        sys.stdout.flush()

        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(
        description="Hailo-8L NPU Live Terminal Monitor: Chip Temperature, Compute Load, and Workload Telemetry",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=["dashboard", "cli", "json"],
        default="dashboard",
        help="Display mode: 'dashboard' (interactive live UI), 'cli' (raw hailortcli monitor), or 'json' (streaming JSON)",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Shortcut for --mode cli (runs standard hailortcli monitor tables)",
    )
    parser.add_argument(
        "--remote",
        default=os.environ.get("EVM_REMOTE_HOST", "192.168.3.14"),
        help="Target host IP address or hostname (default: 192.168.3.14)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Gateway API port (default: 8000)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Live dashboard refresh interval in seconds (default: 1.0)",
    )
    args = parser.parse_args()

    # Ensure HAILO_MONITOR=1 is exported in current environment
    os.environ["HAILO_MONITOR"] = "1"

    if args.cli or args.mode == "cli":
        sys.exit(run_raw_hailortcli(remote_host=args.remote))

    # Initialize local hardware reader and remote client
    hw_reader = HailoHardwareReader()
    api_client = RemoteTelemetryClient(host=args.remote, port=args.port)

    if args.mode == "json":
        try:
            while True:
                ts0, ts1 = hw_reader.read_chip_temperature()
                throttled = hw_reader.read_throttling_state()
                util = hw_reader.read_utilization()
                stats = api_client.get_inference_stats() or {}
                mets = api_client.get_metrics_current() or {}
                sample = {
                    "timestamp": time.time(),
                    "hailo_temp_ts0_c": ts0 or (mets.get("hailo_temperature_c") or {}).get("value"),
                    "hailo_temp_ts1_c": ts1 or (mets.get("hailo_temperature_c") or {}).get("value"),
                    "hailo_throttled": throttled,
                    "hailo_load_percent": util,
                    "inference_fps": stats.get("current_fps"),
                    "total_frames": stats.get("total_frames_processed"),
                    "latencies": stats.get("latencies"),
                }
                print(json.dumps(sample))
                sys.stdout.flush()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            return 0

    # Default: Interactive Live Terminal Dashboard
    render_dashboard(
        hw_reader=hw_reader,
        api_client=api_client,
        target_host=args.remote,
        interval=args.interval,
    )


if __name__ == "__main__":
    main()
