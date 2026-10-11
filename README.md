# edge-vision-monitor

[![License: BSD 3-Clause](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![Hailo-8L](https://img.shields.io/badge/NPU-Hailo--8L%20AI%20HAT%2B-blueviolet.svg)](https://hailo.ai/)
[![Raspberry Pi 5](https://img.shields.io/badge/Platform-Raspberry%20Pi%205-C51A4A.svg)](https://www.raspberrypi.com/)

Production-grade YOLO11 edge AI inference and telemetry platform for the **Raspberry Pi 5** equipped with a **Hailo-8L AI HAT+**. Provides continuous hardware-accelerated object detection, dynamic runtime switching between Hailo-8L NPU and CPU (ONNX Runtime), flexible video input selection and file uploading, real-time hardware thermal and throttling monitoring, non-blocking SQLite time-series persistence, an interactive cyber-dark FastAPI dashboard with live WebSockets, and least-privilege deployment.

---

## 1. Role and Operational Scope

`edge-vision-monitor` is engineered as a continuously operating edge AI monitoring and visual service, rather than a transient benchmarking script.

### 1.1 Core Capabilities
- **Dual-Backend YOLO11 Inference**: Executes compiled Hailo Executable Format (`.hef`) binaries directly on the Hailo-8L NPU (~14 ms, ~27 FPS) or on CPU via ONNX Runtime (~173 ms, ~5.5 FPS), supporting instantaneous dynamic switching at runtime without service restarts.
- **Selectable Video Inputs & File Upload**: Real-time switching between Raspberry Pi Camera Module (CSI), USB webcams (V4L2), and prerecorded video files, complete with in-dashboard video uploading and playback controls.
- **Hardware & System Telemetry**: Verifiable metrics collected independently of the inference pipeline via Linux `hwmon`, thermal zones, `/proc/stat` delta calculations, and `vcgencmd get_throttled` bitfield decoding.
- **Persistent Time-Series Records**: SQLite in Write-Ahead Logging (`WAL`) mode with asynchronous batched commits, query downsampling, automated retention pruning, and CSV export.
- **FastAPI Dashboard & WebSocket**: Live visualised detection stream (MJPEG), 5 Hz real-time WebSocket state distribution, Chart.js historical trend plots, and hardware diagnostics modal.
- **Reproducible Deployment**: Least-privilege configuration with isolated device access (`/dev/hailo0`, `/dev/video*`), read-only sysfs mounts, and health checks distinguishing web liveness from inference readiness.

### 1.2 Design Principles
In accordance with production deployment requirements:
- No artificial experimental lifecycles, fixed five-minute windows, or mandatory 5,000-frame batches.
- No automated cooldown cycles or synthetic warm-up phases.
- No fabricated hardware metrics; unsupported sensors are explicitly reported as `UNSUPPORTED` or `UNAVAILABLE` rather than substituted with zero or simulated values.
### 1.3 Documentation Suite
Detailed user and operational guides are provided in the `docs/` directory:
- 📖 **[User Guide](docs/user-guide.md)**: Live dashboard interface, video source switching, telemetry gauges, and dataset export.
- ⚙️ **[Configuration Guide](docs/configuration-guide.md)**: Full YAML schema reference, environment variable overrides, and operational recipes.
- 🚀 **[Deployment & Operations Guide](docs/deployment-and-operations.md)**: Physical HAT assembly, PCIe Gen 3 setup, Podman containerisation, and systemd units.
- 🔧 **[Troubleshooting & Diagnostics](docs/troubleshooting-and-diagnostics.md)**: Automated environment audits (`scripts/diagnose.py`), PCIe link training, and error remediation.
- 🌐 **[REST API & WebSocket Reference](docs/api-reference.md)**: Complete endpoint specifications, request/response JSON schemas, and streaming protocol.

---

## 2. Architecture Overview

The application adopts a decoupled producer-consumer architecture implemented in Python 3 using `asyncio` for API serving and dedicated worker threads for blocking device I/O:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        VIDEO SOURCE MANAGER                            │
│  [Raspberry Pi Camera Module]    [USB Webcam]    [Prerecorded Video]   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Bounded Frame Queue (Drop-Stale)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      HAILO YOLO11 INFERENCE ENGINE                     │
│  Letterbox Resize  ──►  Hailo-8L NPU (PCIe)  ──►  YOLO11 Decode & NMS  │
└───────────┬────────────────────────────────────────────────┬───────────┘
            │                                                │
   Annotated Preview JPEG                                Detections & Latencies
            │                                                │
            ▼                                                ▼
┌───────────────────────┐                        ┌───────────────────────┐
│   FASTAPI DASHBOARD   │                        │  SQLITE STORAGE WORKER│
│  • Live MJPEG Stream  │                        │  • Batched WAL writes │
│  • WebSocket Broadcast│                        │  • Automated Pruning  │
│  • Chart.js Visualiser│                        │  • CSV Dataset Export │
└───────────▲───────────┘                        └───────────▲───────────┘
            │                                                │
┌───────────┴────────────────────────────────────────────────┴───────────┐
│                      INDEPENDENT TELEMETRY COLLECTOR                   │
│  • Linux hwmon (RP1 & SoC)              • CPU Utilisation & Deltas     │
│  • Thermal Zones (/sys/class/thermal)   • vcgencmd Throttling Bitfields│
│  • Hailo NPU Device & Driver            • Process & cgroup v2 RAM/CPU  │
└────────────────────────────────────────────────────────────────────────┘
```

### Architectural Principles
- **Backpressure & Queue Isolation**: Frame queues between video acquisition and inference are strictly bounded (depth: 2) with a drop-stale policy to eliminate latency build-up.
- **Latency Separation**: Accelerator execution duration (`hailo_exec_ms`) is tracked with monotonic timers and strictly separated from image preprocessing, post-processing, and end-to-end pipeline latency.
- **Independent Telemetry Scheduling**: Hardware sensor polling operates on an independent thread, ensuring slow filesystem or driver reads never block frame capture or neural network execution.

---

## 3. Hardware & Software Prerequisites

### Target Hardware
- **Single Board Computer**: Raspberry Pi 5 (4GB or 8GB RAM recommended).
- **AI Accelerator**: Hailo-8L AI HAT+ connected via the 16-pin PCIe FPC interface.
- **Camera Input**: Raspberry Pi Camera Module 3 / v2 (CSI ribbon), standard UVC USB webcam, or prerecorded video.
- **Optional Environmental Sensors**: INA219 voltage/current monitor (I²C bus 1, address `0x40`), compatible PWM cooling fan with tachometer feedback.

### Host Software
- **Operating System**: Raspberry Pi OS 64-bit (Debian Bookworm) with Linux kernel 6.6 or later.
- **Hailo Drivers**:
  ```bash
  sudo apt update
  sudo apt install -y hailo-all
  ```
  Verify device detection:
  ```bash
  lspci -d 1e60:
  # Expected: Co-processor: Hailo Technologies Ltd. Hailo-8 AI Processor
  ls -l /dev/hailo0
  ```
- **Python**: Python 3.10, 3.11, or 3.12 with `python3-venv`.
- **Container Engine**: Podman 4.3+ (`sudo apt install podman`).

---

## 4. Model Provisioning

The application does not fabricate or bundle uncompiled models. Real Hailo-8L acceleration requires compiled **Hailo Executable Format (`.hef`)** binaries.

### 4.1 Supplying the Compiled Model
1. Place your compiled YOLO11 `.hef` file in the `models/` directory:
   ```text
   models/
   ├── yolo11n.hef         # Compiled Hailo-8L executable
   ├── labels.txt          # Class names (one per line, COCO-80 default provided)
   └── README.md           # Model compilation reference guide
   ```
2. To train, optimize, or compile YOLO11 targeting the Hailo-8L, utilise the companion repository [**hailo-yolo11-compiler**](https://github.com/imosudi/hailo-yolo11-compiler):
   ```bash
   yolo export model=yolo11n.pt format=onnx opset=11
   hailo-yolo11-compiler compile --onnx yolo11n.onnx --target hailo8l --output models/yolo11n.hef
   ```
3. Verify model integrity on the Raspberry Pi 5:
   ```bash
   hailortcli parse-hef models/yolo11n.hef
   ```

### 4.2 Startup Model Validation
Upon application start, the engine verifies:
1. File accessibility and minimum binary size.
2. HailoRT Python bindings availability (`hailo_platform`).
3. Hardware device node presence (`/dev/hailo0`).
4. Correctness of input stream shapes and detection heads.

If physical hardware or model files are absent, the engine reports an explicit status (`NO_RUNTIME`, `DEVICE_NOT_FOUND`, or `MOCK_ACTIVE`) and enables simulated execution for testing without misrepresenting hardware state.

---

## 5. Native Installation & Quickstart

```bash
# 1. Clone repository
git clone https://github.com/imosudi/edge-vision-monitor.git
cd edge-vision-monitor

# 2. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies in editable mode
pip install --upgrade pip
pip install -e ".[dev]"

# 4. Execute hardware diagnostics
python scripts/diagnose.py

# 5. Start the Edge Vision Monitor server
python -m app.main
```

Navigate to **`http://localhost:8000`** in any modern web browser.

---

## 6. Podman Container Deployment

Deployment via Podman adheres to **least-privilege host access**, avoiding `--privileged` and unrestricted root mounts.

### 6.1 Building the Container
```bash
podman build -t edge-vision-monitor:latest -f Containerfile .
```

### 6.2 Running with Podman Compose
```bash
# Start background service
podman-compose up -d

# Inspect running container and health status
podman-compose ps

# View structured operational logs
podman-compose logs -f
```

### 6.3 Direct Podman Command Line
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

### 6.4 Container Health Monitoring
The container health check distinguishes HTTP process liveness from accelerator readiness:
- **Liveness** (`/api/v1/health`): Verifies the Uvicorn ASGI server and background telemetry threads are actively cycling.
- **Readiness** (`/api/v1/ready`): Queries HailoRT VDevice state and model configuration.

---

## 7. Video Input Configuration

The platform supports dynamic, runtime source switching across three modalities:

### 7.1 Raspberry Pi Camera Module (CSI)
- Interfaces with the hardware sensor via `Picamera2` and host `libcamera`.
- Frame dimensions and target capture frame rate are negotiated dynamically.
- When containerised, requires either host camera socket access or host device pass-through.

### 7.2 USB Webcam (V4L2)
- Enumerates available devices via `/dev/v4l/by-id/` and `/dev/video*`.
- Includes automated disconnection detection; if read failures exceed ten consecutive frames, the handle is cleanly recycled with exponential backoff.

### 7.3 Prerecorded Video Files
- Video files placed in `media/` (`.mp4`, `.avi`, `.mkv`, `.mov`) can be selected via REST API or the dashboard dropdown.
- Playback pacing respects the native video FPS.
- Interactive controls: **Play**, **Pause**, **Restart**, and configurable **Looping**.
- Path-traversal protection prevents access outside the configured `media_dir`.
- In the absence of physical media, a procedural synthetic edge stream generates moving geometric targets for testing.

---

## 8. Hardware Telemetry & Metric Catalogue

Hardware monitoring is implemented through native Linux interfaces rather than static estimations:

| Metric Identifier | Units | Source Interface | Description |
|---|---|---|---|
| `cpu_utilisation` | `%` | `/proc/stat` deltas | True host CPU utilisation calculated from successive counter differences |
| `cpu_freq_cpu*_mhz` | `MHz` | `/sys/devices/system/cpu/` | Per-core current clock frequencies |
| `memory_utilisation` | `%` | `/proc/meminfo` | Host RAM utilisation calculated from MemTotal and MemAvailable |
| `memory_available_mb` | `MB` | `/proc/meminfo` | Available system memory in megabytes |
| `thermal_*_temp` | `°C` | `/sys/class/thermal/` | Thermal zone temperatures (converted from millidegrees Celsius) |
| `hwmon_*_temp` | `°C` | `/sys/class/hwmon/` | Hardware monitor chip temperatures (RP1, SoC) |
| `hwmon_*_rpm` | `RPM` | `/sys/class/hwmon/` | Cooling fan tachometer feedback |
| `rpi_throttled_raw` | `flags` | `vcgencmd get_throttled` | Raw hexadecimal throttling bitfield |
| `rpi_undervoltage_now` | `boolean` | `vcgencmd get_throttled` | Active under-voltage flag (Bit 0) |
| `rpi_is_throttled` | `boolean` | `vcgencmd get_throttled` | Active throttling condition (Bits 0–3) |
| `hailo_device_present` | `boolean` | `/dev/hailo0` | Hailo PCIe device node detection |
| `hailo_temperature_c` | `°C` | HailoRT / driver | Accelerator silicon temperature (reported as `UNSUPPORTED` if driver does not expose it) |
| `hailo_power_watts` | `Watts` | HailoRT / INA219 | Accelerator power consumption |
| `process_memory_rss_mb` | `MB` | `/proc/self/status` | Resident Set Size memory of the monitoring process |
| `container_cgroup_memory_mb` | `MB` | `/sys/fs/cgroup/` | Container cgroup v2 memory consumption |

### Availability States
Every metric sample carries an explicit state attribute:
- `AVAILABLE`: Sensor reading successfully acquired and normalised.
- `UNAVAILABLE`: Hardware device expected but temporarily unreachable or disconnected.
- `UNSUPPORTED`: Interface not exposed by target host kernel, driver, or virtualised container.
- `PERMISSION_DENIED`: File or device node exists but requires elevated user permissions.
- `STALE`: Reading older than the configured freshness window.
- `READ_ERROR`: Transient I/O or parsing failure.

---

## 9. Configuration Reference

Configuration is managed via `config/config.yaml` with environment variable overrides formatted as `EVM_SECTION__KEY`:

```yaml
# Model and Hailo Accelerator
model:
  hef_path: "models/yolo11n.hef"
  labels_path: "models/labels.txt"
  metadata_path: null
  input_width: null            # Auto-discovered from HEF if null
  input_height: null           # Auto-discovered from HEF if null
  confidence_threshold: 0.25   # Range: 0.0 to 1.0
  nms_iou_threshold: 0.45      # Range: 0.0 to 1.0
  max_detections: 100

# Video Input Sources
video:
  default_source_type: "file"  # "picamera", "usb", or "file"
  picamera_camera_num: 0
  usb_device_path: "/dev/video0"
  video_file_path: "media/sample.mp4"
  media_dir: "media"
  capture_width: 640
  capture_height: 480
  capture_fps: 30
  loop_playback: true

# Telemetry Sampling & Alarms
telemetry:
  system_interval_seconds: 1.0
  hailo_interval_seconds: 0.5
  enable_hwmon: true
  enable_thermal: true
  enable_raspberry_pi: true
  enable_hailo: true
  enable_process: true
  enable_ina219: false
  ina219_i2c_bus: 1
  ina219_i2c_address: 0x40
  thresholds:
    warning_cpu_temp_c: 75.0
    critical_cpu_temp_c: 85.0
    warning_hailo_temp_c: 80.0
    critical_hailo_temp_c: 90.0

# SQLite Persistence
storage:
  db_path: "data/telemetry.db"
  retention_days: 7
  batch_size: 50
  flush_interval_seconds: 1.0

# HTTP & Web Dashboard
server:
  host: "127.0.0.1"            # Bind loopback for least privilege; "0.0.0.0" for LAN
  port: 8000
  log_level: "INFO"
  preview_max_fps: 15
  preview_quality: 75
```

---

## 10. REST API Specification

All application endpoints are versioned under `/api/v1/`:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/health` | Process liveness, uptime, and worker health |
| `GET` | `/api/v1/ready` | Hailo device, model validation, and accelerator readiness |
| `GET` | `/api/v1/status` | Current application state, active input source, and alarm counts |
| `GET` | `/api/v1/metrics/current` | Snapshot of all latest normalised hardware telemetry readings |
| `GET` | `/api/v1/metrics/history` | Historical time-series query with optional metric filter and downsampling |
| `GET` | `/api/v1/metrics/catalog` | Discovered sensor catalogue, units, and provenance |
| `GET` | `/api/v1/inference/stats` | Rolling FPS, total frame counters, and latency percentiles (mean, p95, p99) |
| `GET` | `/api/v1/detections/latest` | Structured detections for the most recently evaluated frame |
| `GET` | `/api/v1/video/sources` | Discovered input devices (CSI camera, USB devices, media files) |
| `POST` | `/api/v1/video/source` | Switch active video input safely |
| `POST` | `/api/v1/video/playback` | Playback control (`play`, `pause`, `restart`) for prerecorded video |
| `POST` | `/api/v1/inference/start` | Start or resume continuous inference execution |
| `POST` | `/api/v1/inference/stop` | Stop continuous inference execution safely |
| `GET` | `/api/v1/video/stream` | Multipart live MJPEG preview stream with bounding box overlays |
| `GET` | `/api/v1/video/frame` | Single annotated JPEG frame snapshot |
| `GET` | `/api/v1/system/info` | Host hardware, CPU model, kernel, and driver version details |
| `GET` | `/api/v1/history/export/telemetry` | Export persisted telemetry records as a downloadable CSV dataset |
| `GET` | `/api/v1/history/export/detections` | Export persisted object detections as a downloadable CSV dataset |
| `WS` | `/api/v1/ws` | High-frequency WebSocket publishing live telemetry and detections at 5 Hz |

---

## 11. Web Dashboard Visualisation

The browser dashboard is served directly from the embedded FastAPI service at `http://localhost:8000`.

- **Live Inference Viewport**: Renders the annotated stream with bounding boxes, class tags, and confidence percentages. Overlaid Heads-Up Display (HUD) shows live FPS, Hailo NPU latency, and object counts.
- **Source Switching Bar**: Tabbed interface permitting on-the-fly transitions between prerecorded files, USB webcams, and Raspberry Pi CSI cameras with playback controls.
- **Hardware Thermals & Resources**: Real-time gauge bars for CPU temperature, RP1 temperature, Hailo NPU temperature, RAM utilisation, and storage capacity.
- **Throttling Alert Banner**: Animates into view whenever Raspberry Pi under-voltage or thermal throttling flags are detected by `vcgencmd`.
- **Latency Breakdown**: Visualises time spent across Preprocessing, Hailo Accelerator Execution, and Post-processing.
- **Historical Trend Visualisation**: Interactive Chart.js graphs tracking latencies, inference FPS, thermal profiles, and host load over time.
- **Diagnostics Modal**: Displays target system specifications, full sensor catalogue, and CSV export shortcuts.

---

## 12. Storage & Retention Behaviour

The persistence service uses embedded SQLite with `WAL` (Write-Ahead Logging) mode enabled:
- **Non-Blocking Queue**: Telemetry and frame statistics are enqueued to a bounded memory buffer. A dedicated background thread drains the queue in transactions of up to 50 items or every 1.0 second.
- **Schema**:
  - `telemetry_samples`: Timestamp, monotonic time, metric name, normalised value, unit, source interface, status, and error message.
  - `inference_frames`: Sequence number, source ID, latencies (acquisition, preprocessing, Hailo execution, post-processing, total), detection count, dropped flag.
  - `detections`: Bounding box normalised coordinates (`xmin`, `ymin`, `xmax`, `ymax`), class ID, label, confidence.
  - `system_events`: Lifecycle events, source transitions, and hardware warning alarms.
- **Automated Retention**: Historical records exceeding `storage.retention_days` (default: 7 days) are purged during maintenance sweeps.

---

## 13. Testing & Operational Verification

### Automated Test Suite
Run tests with `pytest`:
```bash
# Execute all unit and hardware-independent integration tests
pytest -v

# Execute with code coverage
pytest --cov=app tests/
```

- **Unit Tests** (`tests/unit/`): Configuration validation, letterbox scaling mathematics, vectorised NMS suppression, unletterbox coordinate inversion, `vcgencmd` bitfield decoding, and SQLite WAL batching.
- **Integration Tests** (`tests/integration/`): FastAPI endpoints via TestClient, VideoSourceManager source transitions, and ApplicationLifecycleManager startup/teardown.
- **Physical Hardware Tests** (`tests/hardware/`): Verifies live PCIe communication with `/dev/hailo0` and CSI camera hardware on the Raspberry Pi 5. Skips gracefully with informative messages when executed on developer workstations lacking Hailo hardware.

---

## 14. Hardware Diagnostic Tool

Execute the diagnostic script to audit your edge environment without modifying any system configuration:

```bash
python scripts/diagnose.py
```

Inspects:
- Raspberry Pi hardware model (`/proc/device-tree/model`).
- PCIe devices (`lspci -d 1e60:`) and `/dev/hailo0` device node.
- Kernel driver presence (`hailo_pci`).
- HailoRT Python bindings (`hailo_platform`).
- Video devices (`/dev/video*`) and Picamera2 availability.
- Thermal zones and hwmon sensors.
- Raspberry Pi throttling bitfields (`vcgencmd get_throttled`).
- User group membership (`video`, `i2c`).

---

## 15. Operational Procedures: Shutdown, Restart & Upgrades

### Graceful Teardown
When terminating the application (via `Ctrl+C`, `SIGTERM`, or container stop):
1. The inference worker stops pulling frames and releases device queues.
2. The active video source worker releases camera hardware locks.
3. The telemetry collector stops background polling.
4. The Hailo inference engine closes configured VDevice streams.
5. The storage repository flushes all pending batches to disk and closes the SQLite connection.

### Container Restart & Upgrade
```bash
# Pull or rebuild updated image
podman-compose build

# Recreate container preserving persistent data in ./data
podman-compose down
podman-compose up -d
```

---

## 16. Security Policy

- **Secure by Default**: Binds to loopback `127.0.0.1` unless explicitly instructed otherwise.
- **Least-Privilege Isolation**: No `--privileged` container mode. Mounts host sysfs read-only (`:ro`).
- **Path Traversal Guards**: Media selection is strictly validated against the configured `media_dir`.
- **No Biometric Processing**: The pipeline strictly classifies standard object categories (COCO-80).
- Detailed reporting guidelines are available in [SECURITY.md](file:///home/mosud/Documents/dev/edge-vision-monitor/SECURITY.md).

---

## 17. Licensing and Academic Provenance

This research software and associated architectural artefacts are published under the open-source **BSD 3-Clause Licence**. Refer to the [LICENSE](LICENSE) file for comprehensive legal terms.

```text
Copyright (c) 2026, Isiaka Mosudi, FHTW.
All rights reserved.

Developed within the academic framework of Master's thesis requirements.
Department of Electronic Engineering and Entrepreneurship,
University of Applied Sciences Technikum Wien (FH Technikum Wien), Vienna, Austria.
```

---

## 18. Citation

If you utilise this software platform, its telemetry architectures, or Hailo/ONNX inference pipelines in academic research, please cite:

```bibtex
@software{EdgeVisionMonitor2026,
  author    = {Isiaka, Mosudi},
  title     = {Edge Vision Monitor: Production-Grade YOLO11 Edge AI Inference, Telemetry, and Monitoring Platform for Raspberry Pi 5 and Hailo-8L},
  year      = {2026},
  url       = {https://github.com/imosudi/edge-vision-monitor},
  license   = {BSD-3-Clause}
}
```
