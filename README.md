# edge-vision-monitor

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![Hailo-8L](https://img.shields.io/badge/NPU-Hailo--8L%20AI%20HAT%2B-blueviolet.svg)](https://hailo.ai/)
[![Raspberry Pi 5](https://img.shields.io/badge/Platform-Raspberry%20Pi%205-C51A4A.svg)](https://www.raspberrypi.com/)

Production-grade YOLO11 edge AI inference and telemetry platform for **Raspberry Pi 5** equipped with a **Hailo-8L AI HAT+**. Provides continuous hardware-accelerated object detection, dynamic video source switching, real-time hardware thermals and throttling monitoring, non-blocking SQLite time-series history, an interactive cyber-dark FastAPI dashboard, and least-privilege Podman container deployment.

---

## Architecture Overview

`edge-vision-monitor` implements a modular producer-consumer architecture designed to keep inference throughput independent of system telemetry sampling, database persistence, and web client rendering:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        VIDEO SOURCE MANAGER                            │
│  [Raspberry Pi Camera Module]    [USB Webcam]    [Prerecorded Video]   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Bounded Frame Buffer (Drop-Stale)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      HAILO YOLO11 INFERENCE ENGINE                     │
│  Preprocessing  ──►  Hailo-8L NPU (PCIe)  ──►  Post-Processing (NMS)   │
└───────────┬────────────────────────────────────────────────┬───────────┘
            │                                                │
   Annotated Frames (JPEG)                               Detections & Latencies
            │                                                │
            ▼                                                ▼
┌───────────────────────┐                        ┌───────────────────────┐
│   FASTAPI DASHBOARD   │                        │  SQLITE STORAGE WORKER│
│  • Live MJPEG Stream  │                        │  • Batched WAL writes │
│  • WebSocket Telemetry│                        │  • Automatic Pruning  │
│  • Chart.js Historical│                        │  • CSV Dataset Export │
└───────────▲───────────┘                        └───────────▲───────────┘
            │                                                │
┌───────────┴────────────────────────────────────────────────┴───────────┐
│                      INDEPENDENT TELEMETRY COLLECTOR                   │
│  • Linux hwmon (RP1 & SoC)              • CPU Utilisation & Deltas     │
│  • Thermal Zones (/sys/class/thermal)   • vcgencmd Throttling Bitfields│
│  • Hailo NPU Device & Driver            • Process & cgroup v2 RAM/CPU  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Key Capabilities

1. **Hardware-Accelerated YOLO11**:
   - Executes compiled Hailo Executable Format (`.hef`) models directly on the Hailo-8L NPU via HailoRT.
   - Measures raw accelerator latency (`hailo_exec_ms`) separately from preprocessing and post-processing.
   - Graceful fallback to mock mode during development on non-Hailo workstations without faking hardware data.
2. **Dynamic Video Source Switching**:
   - Raspberry Pi Camera Module (CSI) via `Picamera2` / `libcamera`.
   - Selectable USB Webcams with V4L2 device discovery and disconnect recovery.
   - Prerecorded video file playback with native FPS pacing, loop mode, play/pause controls, and path-traversal guards.
   - Procedural synthetic edge video generator for zero-hardware testing.
3. **Comprehensive Hardware Telemetry**:
   - Dynamic `/sys/class/hwmon/` discovery (SoC temperatures, RP1 temperatures, fan RPM, voltages).
   - Dynamic `/sys/class/thermal/` zones and cooling device state.
   - True delta-calculated CPU utilization via successive `/proc/stat` counter sampling.
   - Raspberry Pi `vcgencmd get_throttled` bitfield decoding (current and past undervoltage, frequency capping, thermal throttling).
   - Optional INA219 current and power sensor integration over I2C.
4. **Persistent Time-Series & Event Storage**:
   - Embedded SQLite configured in Write-Ahead Logging (`WAL`) mode.
   - Bounded in-memory queues and background batch writer workers that never block capture or inference loops.
   - Time-series queries with downsampling, automated retention purging, and CSV export.
5. **Interactive Dashboard & REST API**:
   - Cyber-dark glassmorphic UI built with Vanilla CSS and Google Inter typography.
   - Real-time WebSocket feed distributing live detections, HUD stats, and hardware metrics at 5 Hz.
   - Historical time-series plots powered by Chart.js.
   - Versioned REST API under `/api/v1/`.

---

## Hardware & Software Prerequisites

- **Host Machine**: Raspberry Pi 5 (ARM64 / aarch64) or Linux x86_64 development host.
- **Accelerator**: Hailo-8L AI HAT+ connected via the Raspberry Pi 5 PCIe FPC cable.
- **Operating System**: Raspberry Pi OS 64-bit (Debian Bookworm) with kernel 6.6+.
- **Hailo Drivers**:
  - `hailo-all` debian package (`sudo apt install hailo-all`)
  - PCIe device node `/dev/hailo0` present
- **Python**: Python 3.10, 3.11, or 3.12.

---

## Quickstart: Native Installation

```bash
# 1. Clone repository
git clone https://github.com/imosudi/edge-vision-monitor.git
cd edge-vision-monitor

# 2. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install --upgrade pip
pip install -e ".[dev]"

# 4. Run hardware diagnostics
python scripts/diagnose.py

# 5. Start Edge Vision Monitor
python -m app.main
```

Open your browser to: **`http://localhost:8000`**

---

## Model Provisioning

Hailo-8L executes compiled `.hef` files. To supply a model:

1. Obtain or compile a YOLO11 model targeting Hailo-8L (e.g. using the companion `hailo-yolo11-compiler`):
   ```bash
   yolo export model=yolo11n.pt format=onnx opset=11
   # Compile with Hailo Dataflow Compiler
   hailo-yolo11-compiler compile --onnx yolo11n.onnx --target hailo8l --output models/yolo11n.hef
   ```
2. Copy `yolo11n.hef` to `models/yolo11n.hef`.
3. Ensure class labels are defined in `models/labels.txt` (standard COCO-80 provided by default).
4. See [models/README.md](file:///home/mosud/Documents/dev/edge-vision-monitor/models/README.md) for full instructions.

---

## Podman Deployment (Least-Privilege)

The container configuration uses **rootless, least-privilege device mapping** without `--privileged`:

```bash
# 1. Build container image
podman build -t edge-vision-monitor:latest -f Containerfile .

# 2. Deploy using Podman Compose
podman-compose up -d

# 3. Check health and logs
podman-compose ps
podman-compose logs -f
```

### Manual Podman Run Command

```bash
podman run -d \
  --name edge-vision-monitor \
  --network host \
  --device /dev/hailo0:/dev/hailo0:rwm \
  --device /dev/video0:/dev/video0:rwm \
  -v /sys/class/hwmon:/sys/class/hwmon:ro \
  -v /sys/class/thermal:/sys/class/thermal:ro \
  -v $(pwd)/data:/app/data:Z \
  -v $(pwd)/models:/app/models:ro,Z \
  -v $(pwd)/media:/app/media:ro,Z \
  -e EVM_SERVER__HOST=0.0.0.0 \
  -e EVM_SERVER__PORT=8000 \
  edge-vision-monitor:latest
```

---

## Configuration Reference

Configuration can be specified in `config/config.yaml` or overridden via environment variables formatted as `EVM_SECTION__KEY`:

| Environment Variable | YAML Path | Default | Description |
|---|---|---|---|
| `EVM_SERVER__HOST` | `server.host` | `127.0.0.1` | Bind IP (use `0.0.0.0` for LAN access) |
| `EVM_SERVER__PORT` | `server.port` | `8000` | HTTP listening port |
| `EVM_MODEL__HEF_PATH` | `model.hef_path` | `models/yolo11n.hef` | Path to compiled Hailo HEF model |
| `EVM_MODEL__CONFIDENCE_THRESHOLD` | `model.confidence_threshold` | `0.25` | Detection confidence filter [0.0 - 1.0] |
| `EVM_MODEL__NMS_IOU_THRESHOLD` | `model.nms_iou_threshold` | `0.45` | IoU suppression threshold [0.0 - 1.0] |
| `EVM_VIDEO__DEFAULT_SOURCE_TYPE` | `video.default_source_type` | `file` | Initial source (`picamera`, `usb`, `file`) |
| `EVM_VIDEO__USB_DEVICE_PATH` | `video.usb_device_path` | `/dev/video0` | USB camera device path |
| `EVM_TELEMETRY__SYSTEM_INTERVAL_SECONDS` | `telemetry.system_interval_seconds` | `1.0` | Hardware sampling interval |
| `EVM_STORAGE__DB_PATH` | `storage.db_path` | `data/telemetry.db` | SQLite database file path |
| `EVM_STORAGE__RETENTION_DAYS` | `storage.retention_days` | `7` | History retention before auto-purge |

See [config/config.example.yaml](file:///home/mosud/Documents/dev/edge-vision-monitor/config/config.example.yaml) for all parameters.

---

## REST API Specification

All endpoints are versioned under `/api/v1/`:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/health` | Process liveness, uptime, collector health |
| `GET` | `/api/v1/ready` | Hailo device, model validation and inference readiness |
| `GET` | `/api/v1/status` | Application state, active source, active alarms |
| `GET` | `/api/v1/metrics/current` | Latest snapshot of all hardware telemetry |
| `GET` | `/api/v1/metrics/history` | Historical time-series query with downsampling |
| `GET` | `/api/v1/metrics/catalog` | Discovered sensor catalog and data provenance |
| `GET` | `/api/v1/inference/stats` | Rolling FPS and latency percentiles (mean, p95, p99) |
| `GET` | `/api/v1/detections/latest` | Latest structured object detection records |
| `GET` | `/api/v1/video/sources` | Discovered input sources (CSI, USB, files) |
| `POST` | `/api/v1/video/source` | Switch video source safely |
| `POST` | `/api/v1/video/playback` | Play, pause, or restart prerecorded video |
| `POST` | `/api/v1/inference/start` | Start/resume continuous inference |
| `POST` | `/api/v1/inference/stop` | Stop continuous inference |
| `GET` | `/api/v1/video/stream` | Multipart live MJPEG preview stream |
| `GET` | `/api/v1/video/frame` | Single annotated JPEG frame snapshot |
| `GET` | `/api/v1/system/info` | Host hardware and OS distribution details |
| `GET` | `/api/v1/history/export/telemetry` | Export persisted telemetry samples as CSV |
| `GET` | `/api/v1/history/export/detections` | Export persisted detection records as CSV |
| `WS` | `/api/v1/ws` | Live telemetry, detections, and FPS WebSocket feed |

---

## Testing & Quality Verification

Run the automated test suite with pytest:

```bash
# Run all unit and hardware-independent integration tests
pytest -v

# Run with coverage report
pytest --cov=app tests/
```

- **Unit tests** (`tests/unit/`): Configuration validation, preprocessing letterbox maths, post-processing YOLO decoding/NMS, telemetry bitfields, SQLite WAL batching.
- **Integration tests** (`tests/integration/`): FastAPI endpoints, VideoSourceManager transitions, ApplicationLifecycleManager full lifecycle.
- **Physical hardware tests** (`tests/hardware/`): Validates physical Hailo-8L accelerator and CSI camera (skips automatically on non-Hailo machines).

---

## Diagnostics Tool

Execute the diagnostic script to audit your edge hardware environment:

```bash
python scripts/diagnose.py
```

Checks PCIe device nodes, kernel drivers, HailoRT Python bindings, camera interfaces, thermal zones, firmware throttling flags, and user group permissions without altering system configuration.

---

## Security & Privacy

- Bound to loopback interface (`127.0.0.1`) by default.
- Least-privilege Podman execution with isolated device nodes.
- Path traversal guards restrict media playback to configured directories.
- Object detection is strictly general-purpose (COCO-80 classes). No biometric identification or facial recognition routines exist in this codebase.
- See [SECURITY.md](file:///home/mosud/Documents/dev/edge-vision-monitor/SECURITY.md) for full details.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
