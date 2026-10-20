"""
Custom exceptions and hardware error diagnostic notices for Edge Vision Monitor.
Provides structured error types and formatted terminal notices for hardware device
faults, container runtime errors, and dynamic peripheral discovery issues.
"""

from __future__ import annotations

import sys
from typing import Optional


class EdgeVisionMonitorError(Exception):
    """Base exception for all domain-specific errors in Edge Vision Monitor."""
    pass


class DeviceGatheringError(EdgeVisionMonitorError):
    """
    Raised when container engine (Docker / Podman) or system daemon fails to gather
    device information while attaching a custom hardware device node (e.g. /dev/ttyUSB0).
    """

    def __init__(
        self,
        device_node: str,
        message: Optional[str] = None,
        host: Optional[str] = None,
        remediation: Optional[str] = None,
    ):
        self.device_node = device_node
        self.host = host
        default_msg = f"Error response from daemon: error gathering device information while adding custom device \"{device_node}\": no such file or directory"
        self.message = message or default_msg
        self.remediation = remediation or (
            f"1. Connect the peripheral hardware device corresponding to '{device_node}' (e.g. ESP32-S3 ambient sensor).\n"
            f"2. Pull the latest repository updates on target host (git pull origin main) to switch from static device mappings to dynamic cgroup rules.\n"
            f"3. Verify device detection using: ls -la {device_node} or dmesg | grep -i tty"
        )
        super().__init__(self.message)


class MissingHardwareDeviceError(EdgeVisionMonitorError):
    """Raised when a mandatory hardware device node (e.g. /dev/hailo0 or /dev/video0) is absent."""

    def __init__(self, device_path: str, subsystem: str, remediation: Optional[str] = None):
        self.device_path = device_path
        self.subsystem = subsystem
        self.remediation = remediation or f"Ensure {subsystem} hardware is physically attached and driver module is loaded."
        super().__init__(f"Mandatory hardware device '{device_path}' for {subsystem} is unavailable.")


def print_missing_device_notice(
    device_node: str = "/dev/ttyUSB0",
    host: Optional[str] = None,
    raw_error: Optional[str] = None,
) -> None:
    """
    Display a prominent, formatted terminal notice when Docker daemon fails to gather
    hardware device information (such as missing /dev/ttyUSB0).
    """
    clr_reset = "\033[0m" if sys.stdout.isatty() else ""
    clr_bold = "\033[1m" if sys.stdout.isatty() else ""
    clr_red = "\033[31;1m" if sys.stdout.isatty() else ""
    clr_yellow = "\033[33;1m" if sys.stdout.isatty() else ""
    clr_cyan = "\033[36;1m" if sys.stdout.isatty() else ""
    clr_white = "\033[37;1m" if sys.stdout.isatty() else ""
    clr_dim = "\033[2m" if sys.stdout.isatty() else ""

    host_tag = f" [Target Host: {host}]" if host else ""
    err_text = raw_error or f"Error response from daemon: error gathering device information while adding custom device \"{device_node}\": no such file or directory"

    sys.stderr.write(f"\n{clr_red}================================================================================{clr_reset}\n")
    sys.stderr.write(f"{clr_yellow}⚠️  HARDWARE DEVICE EXCEPTION & NOTIFICATION{clr_white}{host_tag}{clr_reset}\n")
    sys.stderr.write(f"{clr_red}================================================================================{clr_reset}\n\n")

    sys.stderr.write(f"{clr_bold}Runtime Daemon Error:{clr_reset}\n")
    sys.stderr.write(f"  {clr_red}{err_text}{clr_reset}\n\n")

    sys.stderr.write(f"{clr_bold}Root Cause Analysis:{clr_reset}\n")
    sys.stderr.write(f"  The container engine attempted to bind-mount the device node '{clr_cyan}{device_node}{clr_reset}',\n")
    sys.stderr.write(f"  but this character device does not exist on the target system filesystem.\n")
    if "ttyUSB" in device_node or "ttyACM" in device_node:
        sys.stderr.write(f"  This corresponds to the ESP32-S3 ambient temperature/humidity sensor board.\n")
        sys.stderr.write(f"  When a container compose file specifies '{device_node}' under static 'devices:',\n")
        sys.stderr.write(f"  Docker strictly requires the physical device to be present before starting.\n\n")

    sys.stderr.write(f"{clr_bold}Recommended Resolution Steps:{clr_reset}\n")
    sys.stderr.write(f"  {clr_yellow}1. Update Remote Compose File (Dynamic Hotplug Mode):{clr_reset}\n")
    sys.stderr.write(f"     Run {clr_white}'git pull origin main'{clr_reset} on the target host. The latest configuration\n")
    sys.stderr.write(f"     uses dynamic device cgroup rules ({clr_cyan}c *:* rmw{clr_reset}) and mounts {clr_cyan}/dev:/dev{clr_reset},\n")
    sys.stderr.write(f"     allowing containers to launch cleanly even if the sensor is temporarily detached.\n\n")

    sys.stderr.write(f"  {clr_yellow}2. Verify Physical USB Connection:{clr_reset}\n")
    sys.stderr.write(f"     Check if the ESP32-S3 module is connected to a Raspberry Pi USB port:\n")
    sys.stderr.write(f"     {clr_white}ls -la /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || dmesg | tail -n 20{clr_reset}\n\n")

    sys.stderr.write(f"  {clr_yellow}3. Autonomous Telemetry Operation:{clr_reset}\n")
    sys.stderr.write(f"     The telemetry collector operates resiliently: if '{device_node}' is absent,\n")
    sys.stderr.write(f"     all other CPU, Hailo NPU, memory, and system metrics continue streaming normally.\n")

    sys.stderr.write(f"\n{clr_red}================================================================================{clr_reset}\n\n")
    sys.stderr.flush()
