# Edge Vision Monitor: Troubleshooting & Diagnostics Guide

This guide details fault-isolation procedures, common operational errors, and diagnostic techniques for the **Edge Vision Monitor** platform.

---

## 1. Automated Health Audit Tool

Before troubleshooting manually, run the standalone diagnostic tool:

```bash
python scripts/diagnose.py
```

This utility performs a non-destructive audit of:
- Raspberry Pi hardware model and Linux kernel distribution.
- PCIe devices (`lspci -d 1e60:`) and `/dev/hailo0` node presence.
- Hailo kernel driver (`hailo_pci`) and Python runtime bindings.
- Video camera inputs (`Picamera2`, `/dev/video*`).
- Linux thermal zones and `hwmon` sensor nodes.
- Raspberry Pi firmware throttling bitfields (`vcgencmd get_throttled`).
- User group access (`video`, `i2c`).

---

## 2. Common Failure Modes & Remedies

### Issue 1: `/dev/hailo0` Device Node Missing
**Symptoms**:
- Hailo status badge displays amber `"Hailo-8L: Missing"`.
- `scripts/diagnose.py` reports `Device Node /dev/hailo0: [NOT FOUND]`.

**Root Causes & Remedies**:
1. **PCIe Ribbon Cable Not Properly Seated**:
   - Power off the system.
   - Inspect both ends of the 16-pin FPC ribbon cable.
   - Ensure the cable is inserted squarely with the contacts facing the correct direction and the black locking bar fully clamped down.
2. **PCIe Overlay Missing in Firmware**:
   - Verify that `/boot/firmware/config.txt` contains:
     ```ini
     dtparam=pciex1
     dtparam=pciex1_gen=3
     ```
   - Reboot the host after saving changes.
3. **Kernel Driver Not Loaded**:
   - Run `lsmod | grep hailo`.
   - If missing, reload the driver manually:
     ```bash
     sudo modprobe hailo_pci
     dmesg | grep -i hailo
     ```

---

### Issue 2: `hailo_platform` Python Module Not Found
**Symptoms**:
- API readiness reports `NO_RUNTIME`.
- Diagnostic script reports `HailoRT Python Bindings: [NOT INSTALLED]`.

**Root Causes & Remedies**:
1. **Python ABI Mismatch**:
   - HailoRT Python wheels are compiled for specific Python versions (typically Python 3.10, 3.11, or 3.12).
   - Verify Python version in your virtual environment:
     ```bash
     python --version
     ```
2. **Missing System Package**:
   - Ensure the `hailo-all` metapackage is installed:
     ```bash
     sudo apt install -y hailo-all
     ```
   - If using a virtual environment, ensure system site-packages are accessible, or link the Hailo package into the virtual environment:
     ```bash
     python3 -m venv --system-site-packages .venv
     ```

---

### Issue 3: Incompatible or Uncompiled Model File
**Symptoms**:
- API readiness displays `INVALID_FORMAT` or `CONFIG_ERROR`.
- Error log indicates `Failed to load HEF`.

**Root Causes & Remedies**:
- Generic PyTorch (`.pt`) or ONNX (`.onnx`) files cannot be loaded by HailoRT directly.
- Ensure the model was compiled specifically for the **Hailo-8L** using the Hailo Dataflow Compiler (DFC):
  ```bash
  hailortcli parse-hef models/yolo11n.hef
  ```
- Check that output tensor stream names match your YOLO post-processing configuration.

---

### Issue 4: Camera Device Busy or Permission Denied
**Symptoms**:
- CSI or USB camera source fails to start (`Could not open device`).
- Error status shows `Permission denied` or `Device or resource busy`.

**Root Causes & Remedies**:
1. **Conflicting Camera Services**:
   - Another process (e.g. `libcamera-vid`, `motion`, or a dangling OpenCV worker) holds the device handle.
   - Identify holding processes:
     ```bash
     fuser /dev/video0
     ```
   - Kill dangling camera processes:
     ```bash
     sudo fuser -k /dev/video0
     ```
2. **Missing Video Group Membership**:
   - The user must belong to the `video` group:
     ```bash
     sudo usermod -aG video $USER
     ```

---

### Issue 5: Under-voltage & Throttling Alert Active
**Symptoms**:
- Amber/red warning banner appears on the dashboard: `Warning: Hardware undervoltage detected!`.
- Telemetry shows `rpi_undervoltage_now = 1.0`.

**Root Causes & Remedies**:
1. **Insufficient Power Supply**:
   - The Raspberry Pi 5 requires a dedicated **5V / 5A (27W)** Power Delivery (PD) power supply when running heavy NPU workloads and active cooling simultaneously. Standard 15W phone chargers will drop below 4.75V under load.
2. **Thermal Saturation**:
   - If temperatures exceed 80°C, the Broadcom BCM2712 SoC drops frequency from 2.4 GHz to 1.5 GHz.
   - Install the official Raspberry Pi Active Cooler or ensure the cooling fan tachometer is functioning.

---

### Issue 6: SQLite Database Locked
**Symptoms**:
- Log message indicates `database is locked` or `busy timeout`.

**Root Causes & Remedies**:
- The platform uses Write-Ahead Logging (`WAL`), which supports concurrent readers and a single writer.
- If multiple processes attempt direct writes, ensure WAL pragmas are active:
  ```bash
  sqlite3 data/telemetry.db "PRAGMA journal_mode;"
  # Expected output: wal
  ```
- Ensure file ownership on `data/telemetry.db` matches the running application user.
