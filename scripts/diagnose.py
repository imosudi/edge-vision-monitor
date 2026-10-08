#!/usr/bin/env python3
"""
Edge Vision Monitor - Hardware, Driver, and Environment Diagnostic Tool.
Inspects Raspberry Pi 5, Hailo-8L AI HAT+, cameras, thermal zones, and permissions.
Does not alter or modify any system state.
"""

from __future__ import annotations

import glob
import os
import platform
import shutil
import subprocess
import sys


def print_section(title: str):
    print(f"\n{'='*70}\n {title}\n{'='*70}")


def check_rpi_model() -> str:
    model_path = "/proc/device-tree/model"
    if os.path.isfile(model_path):
        try:
            with open(model_path, "r", encoding="utf-8") as f:
                return f.read().strip().rstrip("\x00")
        except Exception:
            pass
    return "Non-Raspberry Pi / Standard Linux PC"


def check_hailo_hardware():
    print_section("HAILO-8L ACCELERATOR DIAGNOSTICS")
    # 1. Device node
    node_exists = os.path.exists("/dev/hailo0")
    print(f"Device Node /dev/hailo0:        {'[FOUND]' if node_exists else '[NOT FOUND]'}")

    # 2. PCIe device via lspci
    lspci_found = False
    try:
        res = subprocess.run(["lspci", "-d", "1e60:"], capture_output=True, text=True, timeout=2.0)
        if res.returncode == 0 and res.stdout.strip():
            print(f"PCIe Device (1e60 Hailo):      [DETECTED] {res.stdout.strip()}")
            lspci_found = True
        else:
            print("PCIe Device (1e60 Hailo):      [NOT DETECTED]")
    except FileNotFoundError:
        print("lspci utility:                 [NOT INSTALLED]")

    # 3. Kernel driver
    driver_exists = os.path.exists("/sys/bus/pci/drivers/hailo_pci")
    print(f"Kernel Driver 'hailo_pci':     {'[LOADED]' if driver_exists else '[NOT LOADED]'}")

    # 4. HailoRT python package
    try:
        import hailo_platform  # type: ignore
        version = getattr(hailo_platform, "__version__", "unknown")
        print(f"HailoRT Python Bindings:       [INSTALLED] version {version}")
    except ImportError:
        print("HailoRT Python Bindings:       [NOT INSTALLED] ('hailo_platform' module missing)")

    # 5. hailortcli utility
    try:
        res = subprocess.run(["hailortcli", "--version"], capture_output=True, text=True, timeout=2.0)
        if res.returncode == 0:
            print(f"hailortcli CLI Tool:           [INSTALLED] {res.stdout.strip()}")
        else:
            print("hailortcli CLI Tool:           [RETURNED ERROR]")
    except FileNotFoundError:
        print("hailortcli CLI Tool:           [NOT INSTALLED]")


def check_cameras():
    print_section("VIDEO CAMERA INPUTS")
    # 1. Picamera2
    try:
        import picamera2  # type: ignore
        print("Picamera2 (CSI Camera):        [AVAILABLE]")
    except ImportError:
        print("Picamera2 (CSI Camera):        [NOT INSTALLED]")

    # 2. V4L2 USB Devices
    video_devs = sorted(glob.glob("/dev/video*"))
    if video_devs:
        print(f"V4L2 Video Devices:            {', '.join(video_devs)}")
    else:
        print("V4L2 Video Devices:            [NONE FOUND]")


def check_thermals_and_sensors():
    print_section("THERMAL & HWMON HARDWARE SENSORS")
    # Thermal zones
    tzs = sorted(glob.glob("/sys/class/thermal/thermal_zone*"))
    print(f"Thermal Zones Found:           {len(tzs)}")
    for tz in tzs:
        name = os.path.basename(tz)
        type_path = os.path.join(tz, "type")
        temp_path = os.path.join(tz, "temp")
        ztype = "unknown"
        ztemp = "N/A"
        try:
            if os.path.exists(type_path):
                with open(type_path, "r") as f:
                    ztype = f.read().strip()
            if os.path.exists(temp_path):
                with open(temp_path, "r") as f:
                    ztemp = f"{int(f.read().strip()) / 1000.0:.1f}°C"
        except Exception:
            pass
        print(f"  - {name} ({ztype}): {ztemp}")

    # Hwmon
    hwmons = sorted(glob.glob("/sys/class/hwmon/hwmon*"))
    print(f"hwmon Sensors Found:           {len(hwmons)}")
    for hw in hwmons:
        hname = os.path.basename(hw)
        chip = "unknown"
        try:
            with open(os.path.join(hw, "name"), "r") as f:
                chip = f.read().strip()
        except Exception:
            pass
        print(f"  - {hname} ({chip})")


def check_rpi_throttling():
    print_section("RASPBERRY PI FIRMWARE & THROTTLING")
    try:
        res = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=1.0)
        if res.returncode == 0:
            print(f"vcgencmd get_throttled:        {res.stdout.strip()}")
        else:
            print("vcgencmd get_throttled:        [UNAVAILABLE]")
    except FileNotFoundError:
        print("vcgencmd utility:              [NOT INSTALLED]")


def check_permissions():
    print_section("PERMISSIONS & USER GROUPS")
    uid = os.getuid()
    print(f"Current UID:                   {uid}")
    try:
        import grp
        groups = [grp.getgrgid(g).gr_name for g in os.getgroups()]
        print(f"User Groups:                   {', '.join(groups)}")
        for req in ("video", "i2c"):
            status = "[MEMBER]" if req in groups else "[NOT A MEMBER]"
            print(f"Group '{req}' Access:         {status}")
    except Exception:
        pass


def main():
    print("\n" + "#"*70)
    print(" EDGE VISION MONITOR - HARDWARE DIAGNOSTIC REPORT")
    print("#"*70)
    print(f"Host Model:                    {check_rpi_model()}")
    print(f"OS & Kernel:                   {platform.platform()} ({platform.release()})")
    print(f"Python Architecture:           {sys.version.split()[0]} ({platform.machine()})")

    check_hailo_hardware()
    check_cameras()
    check_thermals_and_sensors()
    check_rpi_throttling()
    check_permissions()
    print("\n" + "#"*70)
    print(" DIAGNOSTIC SCAN COMPLETE - NO SETTINGS MODIFIED")
    print("#"*70 + "\n")


if __name__ == "__main__":
    main()
