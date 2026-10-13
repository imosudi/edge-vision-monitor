# Edge Vision Monitor: Configuration Guide

This guide details the complete configuration hierarchy, schema attributes, environment variable overrides, and operational tuning parameters for the **Edge Vision Monitor** platform.

---

## 1. Configuration Precedence & Resolution

The application resolves configuration options in the following strict order of precedence (highest to lowest):

1. **Environment Variables**: Formatted as `EVM_SECTION__KEY` (e.g. `EVM_SERVER__PORT=8080`).
2. **Explicit Command-Line / Path Argument**: Path passed during application instantiation.
3. **Environment Variable Path**: Path specified via `EVM_CONFIG_PATH`.
4. **Default Configuration File**: `config/config.yaml` in the working directory.
5. **Built-in Schema Defaults**: Safe defaults declared in Pydantic models in `app/core/config.py`.

---

## 2. Complete Configuration Reference

Create `config/config.yaml` by copying `config/config.example.yaml`:

```yaml
# ==============================================================================
# Model & Hailo Accelerator Settings
# ==============================================================================
model:
  # Initial inference backend ("hailo" or "cpu")
  active_backend: "hailo"

  # Path to compiled Hailo Executable Format (.hef) binary
  hef_path: "models/yolo11n.hef"

  # Path to CPU ONNX model for software fallback and benchmarking
  onnx_path: "models/onnx/model.onnx"

  # Path to class labels file (one label per line or YAML format)
  labels_path: "models/labels.txt"

  # Optional metadata configuration YAML file
  metadata_path: null

  # Input tensor dimensions (null = automatically discover from HEF)
  input_width: null
  input_height: null

  # Confidence threshold for object detection filtering [0.0 to 1.0]
  confidence_threshold: 0.25

  # Non-Maximum Suppression (NMS) Intersection-over-Union threshold [0.0 to 1.0]
  nms_iou_threshold: 0.45

  # Maximum detections to output per frame
  max_detections: 100

# ==============================================================================
# Video Input Source Settings
# ==============================================================================
video:
  # Initial video input source ("picamera", "usb", or "file")
  default_source_type: "file"

  # Picamera2 camera sensor number (0 or 1 on Raspberry Pi 5)
  picamera_camera_num: 0

  # USB camera device path or numeric index
  usb_device_path: "/dev/video0"

  # Prerecorded video file path
  video_file_path: "media/sample.mp4"

  # Restricted directory for video files (guards against path traversal)
  media_dir: "media"

  # Capture dimensions
  capture_width: 640
  capture_height: 480

  # Requested capture frame rate (FPS)
  capture_fps: 30

  # Continuous loop playback for video files
  loop_playback: true

# ==============================================================================
# Hardware Telemetry & Threshold Settings
# ==============================================================================
telemetry:
  # General host telemetry sampling interval in seconds
  system_interval_seconds: 1.0

  # Hailo NPU sampling interval in seconds
  hailo_interval_seconds: 0.5

  # Enable Linux hwmon subsystem polling (/sys/class/hwmon/)
  enable_hwmon: true

  # Enable Linux thermal zone polling (/sys/class/thermal/)
  enable_thermal: true

  # Enable Raspberry Pi sysfs and vcgencmd throttling metrics
  enable_raspberry_pi: true

  # Enable Hailo accelerator device telemetry (/dev/hailo0)
  enable_hailo: true

  # Enable process and container cgroup resource monitoring
  enable_process: true

  # Enable optional INA219 current/power sensor over I²C
  enable_ina219: false
  ina219_i2c_bus: 1
  ina219_i2c_address: 0x40

  # Configurable alarm thresholds
  thresholds:
    warning_cpu_temp_c: 75.0      # Triggers warning alarm at 75°C
    critical_cpu_temp_c: 85.0     # Triggers critical alarm at 85°C
    warning_hailo_temp_c: 80.0    # Triggers warning alarm at 80°C
    critical_hailo_temp_c: 90.0   # Triggers critical alarm at 90°C
    warning_memory_percent: 85.0  # Triggers warning alarm at 85% RAM
    critical_memory_percent: 95.0 # Triggers critical alarm at 95% RAM

# ==============================================================================
# Persistent Time-Series Storage Settings
# ==============================================================================
storage:
  # Path to SQLite database file
  db_path: "data/telemetry.db"

  # History retention in days (older records are pruned automatically)
  retention_days: 7

  # Memory queue batch size before committing SQLite transaction
  batch_size: 50

  # Maximum flush delay in seconds for pending batch commits
  flush_interval_seconds: 1.0

# ==============================================================================
# HTTP Server & Visualisation Settings
# ==============================================================================
server:
  # Network bind address (127.0.0.1 for local; 0.0.0.0 for LAN access)
  host: "127.0.0.1"

  # HTTP listening port
  port: 8000

  # Logging severity level ("DEBUG", "INFO", "WARNING", "ERROR")
  log_level: "INFO"

  # Maximum frame rate for live MJPEG preview stream (prevents network saturation)
  preview_max_fps: 15

  # JPEG compression quality [10 to 100]
  preview_quality: 75
```

---

## 3. Environment Variable Overrides

Any configuration parameter can be overridden using environment variables without modifying configuration files. The naming rule uses double underscores (`__`) to delimit sections:

```text
EVM_<SECTION>__<KEY>=<VALUE>
```

### Common Environment Overrides
```bash
# Allow remote access from LAN
export EVM_SERVER__HOST="0.0.0.0"
export EVM_SERVER__PORT="8080"

# Select USB webcam as default source
export EVM_VIDEO__DEFAULT_SOURCE_TYPE="usb"
export EVM_VIDEO__USB_DEVICE_PATH="/dev/video0"

# Configure model and inference backend
export EVM_MODEL__ACTIVE_BACKEND="hailo"
export EVM_MODEL__HEF_PATH="/opt/models/yolo11n.hef"
export EVM_MODEL__ONNX_PATH="/opt/models/model.onnx"
export EVM_MODEL__CONFIDENCE_THRESHOLD="0.30"

# Adjust telemetry sampling frequency
export EVM_TELEMETRY__SYSTEM_INTERVAL_SECONDS="2.0"
export EVM_STORAGE__RETENTION_DAYS="14"
```

---

## 4. Operational Configuration Recipes

### Recipe A: Production CSI Camera Deployment
For continuous deployment on a headless Raspberry Pi 5 with a Camera Module 3:
```yaml
server:
  host: "0.0.0.0"
  port: 8000
  log_level: "INFO"
  preview_max_fps: 10

video:
  default_source_type: "picamera"
  picamera_camera_num: 0
  capture_width: 1280
  capture_height: 720
  capture_fps: 30

model:
  hef_path: "models/yolo11n.hef"
  confidence_threshold: 0.35

storage:
  retention_days: 14
```

### Recipe B: Low-Power Silent Monitoring Mode
Reduces CPU overhead and thermal output on passively cooled systems:
```yaml
server:
  preview_max_fps: 5
  preview_quality: 60

telemetry:
  system_interval_seconds: 5.0
  hailo_interval_seconds: 2.0

storage:
  batch_size: 100
  flush_interval_seconds: 5.0
```

### Recipe C: High-Fidelity USB Inspection Station
Configured for maximum resolution and detailed logging:
```yaml
server:
  preview_max_fps: 30
  preview_quality: 85

video:
  default_source_type: "usb"
  usb_device_path: "/dev/video0"
  capture_width: 1920
  capture_height: 1080
  capture_fps: 30

model:
  confidence_threshold: 0.20
  nms_iou_threshold: 0.40
```
