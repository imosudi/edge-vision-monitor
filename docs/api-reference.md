# Edge Vision Monitor: REST API & WebSocket Reference

The Edge Vision Monitor platform provides a versioned REST API under `/api/v1/` and a real-time WebSocket endpoint for low-latency state distribution.

---

## 1. REST Endpoints Overview

All endpoints accept and return `application/json` unless otherwise specified.

### Summary Table

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/health` | Process liveness, uptime, and background thread states |
| `GET` | `/api/v1/ready` | Hailo accelerator, model validation, and runtime readiness |
| `GET` | `/api/v1/status` | Current application state, active input source, and alarm count |
| `GET` | `/api/v1/metrics/current` | Snapshot of all latest normalised hardware telemetry readings |
| `GET` | `/api/v1/metrics/history` | Historical time-series query with optional metric filter and downsampling |
| `GET` | `/api/v1/metrics/catalog` | Discovered sensor catalogue, units, and provenance |
| `GET` | `/api/v1/inference/backends` | Query available inference engines (Hailo-8L, CPU ONNX) and model paths |
| `POST` | `/api/v1/inference/backend` | Dynamically switch active inference backend (`hailo` vs `cpu`) at runtime |
| `GET` | `/api/v1/inference/stats` | Rolling FPS, total frame counters, and latency percentiles (mean, p95, p99) |
| `GET` | `/api/v1/detections/latest` | Structured detections for the most recently evaluated frame |
| `GET` | `/api/v1/video/sources` | Discovered input devices (CSI camera, USB devices, media files) |
| `POST` | `/api/v1/video/source` | Switch active video input safely |
| `POST` | `/api/v1/video/upload` | Upload prerecorded MP4/AVI/MKV video into media repository |
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

## 2. Endpoint Specifications

### 2.1 Health & Readiness

#### `GET /api/v1/health`
Checks whether the process is alive and internal background threads are cycling.
```bash
curl -s http://localhost:8000/api/v1/health
```
**Response (200 OK)**:
```json
{
  "status": "healthy",
  "uptime_seconds": 1245.8,
  "telemetry_active": true,
  "inference_active": true,
  "version": "1.0.0"
}
```

---

#### `GET /api/v1/ready`
Inspects HailoRT accelerator device readiness and model configuration.
```bash
curl -s http://localhost:8000/api/v1/ready
```
**Response (200 OK)**:
```json
{
  "ready": true,
  "hailo_ready": true,
  "model_status": "READY",
  "hef_path": "models/yolo11n.hef",
  "error_message": null,
  "is_mock": false
}
```

---

### 2.2 Telemetry & Hardware State

#### `GET /api/v1/metrics/current`
Returns the latest normalised reading for every active sensor.
```bash
curl -s http://localhost:8000/api/v1/metrics/current
```
**Response (200 OK)**:
```json
{
  "cpu_utilisation": {
    "name": "cpu_utilisation",
    "value": 24.5,
    "unit": "percent",
    "source": "proc:stat",
    "status": "AVAILABLE",
    "freshness_seconds": 0.4
  },
  "hwmon_rp1_adc_temp": {
    "name": "hwmon_rp1_adc_temp",
    "value": 52.1,
    "unit": "celsius",
    "source": "hwmon:rp1_adc",
    "status": "AVAILABLE",
    "freshness_seconds": 0.4
  },
  "rpi_is_throttled": {
    "name": "rpi_is_throttled",
    "value": 0.0,
    "unit": "boolean",
    "source": "vcgencmd",
    "status": "AVAILABLE",
    "freshness_seconds": 0.4
  }
}
```

---

#### `GET /api/v1/metrics/history`
Query persisted time-series measurements with optional filtering, striding, bucket aggregation, or LTTB downsampling.

**Parameters**:
- `metric_name` *(string, optional)*: Filter by metric identifier.
- `start_time` *(string, optional)*: ISO-8601 start timestamp.
- `end_time` *(string, optional)*: ISO-8601 end timestamp.
- `limit` *(integer, optional, default: 300)*: Maximum records to return.
- `downsample` *(integer, optional, default: 1)*: Step factor to thin points.
- `target_points` *(integer, optional)*: Target output point count for downsampling algorithms.
- `method` *(string, optional, default: "stride")*: Downsampling algorithm (`"stride"`, `"bucket"`, or `"lttb"`).

```bash
curl -s "http://localhost:8000/api/v1/metrics/history?metric_name=cpu_utilisation&target_points=50&method=lttb"
```

---

#### `GET /api/v1/metrics/downsampled`
High-performance downsampled time-series query specifically tailored for visual graphs and telemetry dashboards.

**Parameters**:
- `metric_name` *(string, required)*: Metric identifier to downsample.
- `start_time` *(string, optional)*: ISO-8601 start timestamp.
- `end_time` *(string, optional)*: ISO-8601 end timestamp.
- `target_points` *(integer, optional, default: 100)*: Target number of display points.
- `method` *(string, optional, default: "lttb")*: Downsampling algorithm (`"lttb"` or `"bucket"`).

```bash
curl -s "http://localhost:8000/api/v1/metrics/downsampled?metric_name=soc_thermal_celsius&target_points=100&method=lttb"
```

---

### 2.3 Inference & Detections

#### `GET /api/v1/inference/backends`
Inspects installed runtimes, hardware accelerator nodes, and model weights for both Hailo-8L and CPU backends.
```bash
curl -s http://localhost:8000/api/v1/inference/backends
```
**Response (200 OK)**:
```json
{
  "current_backend": "hailo",
  "backends": {
    "hailo": {
      "name": "Hailo-8L NPU",
      "available": true,
      "model_path": "models/yolo11n.hef",
      "device_node": "/dev/hailo0",
      "runtime_installed": true
    },
    "cpu": {
      "name": "CPU (ONNX Runtime)",
      "available": true,
      "model_path": "models/onnx/model.onnx",
      "device_node": null,
      "runtime_installed": true
    }
  }
}
```

---

#### `POST /api/v1/inference/backend`
Dynamically transitions the active inference backend between **Hailo-8L** and **CPU (ONNX Runtime)** without stopping or restarting the service.
```bash
curl -s -X POST http://localhost:8000/api/v1/inference/backend \
  -H "Content-Type: application/json" \
  -d '{ "backend": "cpu" }'
```
**Response (200 OK)**:
```json
{
  "status": "switched",
  "backend": "cpu",
  "inference_running": true,
  "engine_status": {
    "type": "CPU (ONNX)",
    "backend": "cpu",
    "ready": true,
    "status": "READY",
    "model_path": "models/onnx/model.onnx",
    "error_message": null,
    "is_mock": false
  }
}
```

---

#### `GET /api/v1/inference/stats`
Returns rolling inference FPS and latency statistics over recent frames.
```bash
curl -s http://localhost:8000/api/v1/inference/stats
```
**Response (200 OK)**:
```json
{
  "is_running": true,
  "current_fps": 28.5,
  "total_frames_processed": 14200,
  "total_errors": 0,
  "latencies": {
    "preprocessing_ms": { "mean": 1.4, "median": 1.3, "p95": 1.8, "min": 1.1, "max": 2.5 },
    "hailo_execution_ms": { "mean": 4.8, "median": 4.7, "p95": 5.2, "min": 4.5, "max": 6.1 },
    "postprocessing_ms": { "mean": 0.9, "median": 0.8, "p95": 1.2, "min": 0.7, "max": 1.9 },
    "total_ms": { "mean": 7.1, "median": 6.9, "p95": 8.1, "min": 6.4, "max": 9.8 }
  }
}
```

---

#### `GET /api/v1/detections/latest`
Structured bounding boxes and class attributions for the most recently evaluated frame.
```bash
curl -s http://localhost:8000/api/v1/detections/latest
```
**Response (200 OK)**:
```json
{
  "count": 2,
  "timestamp_utc": "2026-10-08T20:15:30.450123Z",
  "image_width": 640,
  "image_height": 480,
  "detections": [
    {
      "class_id": 0,
      "class_name": "person",
      "confidence": 0.8845,
      "box": { "xmin": 0.245, "ymin": 0.120, "xmax": 0.450, "ymax": 0.680 }
    },
    {
      "class_id": 2,
      "class_name": "car",
      "confidence": 0.9210,
      "box": { "xmin": 0.610, "ymin": 0.420, "xmax": 0.890, "ymax": 0.750 }
    }
  ]
}
```

---

### 2.4 Video Input Operations

#### `POST /api/v1/video/source`
Transition between camera devices safely without orphaned workers.
```bash
curl -s -X POST http://localhost:8000/api/v1/video/source \
  -H "Content-Type: application/json" \
  -d '{
    "source_type": "usb",
    "device": "/dev/video0",
    "width": 640,
    "height": 480,
    "fps": 30
  }'
```

---

#### `POST /api/v1/video/upload`
Uploads a prerecorded video file (`.mp4`, `.avi`, `.mkv`, `.mov`) into the restricted media repository via `multipart/form-data`.
```bash
curl -s -X POST http://localhost:8000/api/v1/video/upload \
  -F "file=@sample_video.mp4"
```
**Response (200 OK)**:
```json
{
  "status": "uploaded",
  "filename": "sample_video.mp4",
  "path": "media/sample_video.mp4",
  "size_bytes": 14258900
}
```

---

#### `POST /api/v1/video/playback`
Control prerecorded video playback (`play`, `pause`, `restart`).
```bash
curl -s -X POST http://localhost:8000/api/v1/video/playback \
  -H "Content-Type: application/json" \
  -d '{ "action": "pause" }'
```

---

### 2.5 Storage, Retention, & CSV Exports

#### `GET /api/v1/storage/status`
Retrieves database file sizes (primary DB, WAL log, SHM shared memory), record counts, bounded queue metrics, and automated retention history.

```bash
curl -s "http://localhost:8000/api/v1/storage/status"
```

---

#### `POST /api/v1/storage/prune`
Manually triggers retention pruning to delete expired records and maintain disk footprint. Accepts an optional `retention_hours` query parameter override.

```bash
curl -s -X POST "http://localhost:8000/api/v1/storage/prune?retention_hours=24.0"
```

---

#### `GET /api/v1/history/export/telemetry`
Streams persisted hardware and system telemetry samples as a downloadable CSV dataset. Supports optional `metric_name`, `start_time`, `end_time`, and `limit` filters.

```bash
curl -s "http://localhost:8000/api/v1/history/export/telemetry?metric_name=cpu_temp" -o telemetry.csv
```

---

#### `GET /api/v1/history/export/detections`
Streams historical object detection records as a downloadable CSV dataset with frame sequences, class names, confidence ratings, and bounding box coordinates.

```bash
curl -s "http://localhost:8000/api/v1/history/export/detections?class_name=person" -o detections.csv
```

---

#### `GET /api/v1/history/export/waveforms`
Streams a unified multi-channel time-series dataset combining both hardware sensor telemetry and computer vision inference latencies/counts aligned across time.

```bash
curl -s "http://localhost:8000/api/v1/history/export/waveforms" -o waveforms.csv
```

---

## 3. Real-Time WebSocket Protocol

### Endpoint: `ws://<host>:8000/api/v1/ws`

The WebSocket connection delivers low-latency JSON packets broadcast at **5 Hz** (~200ms intervals) to active clients:

```json
{
  "type": "telemetry_update",
  "timestamp_utc": "2026-10-08T20:15:30.450123Z",
  "status": {
    "inference_running": true,
    "active_source": "usb:/dev/video0",
    "source_type": "usb",
    "active_backend": "hailo"
  },
  "inference": {
    "active_backend": "hailo",
    "backend_name": "Hailo-8L",
    "fps": 27.2,
    "latencies": {
      "execution_ms": { "mean": 14.1, "p95": 14.8 },
      "hailo_execution_ms": { "mean": 14.1, "p95": 14.8 },
      "preprocessing_ms": { "mean": 0.7, "p95": 1.0 },
      "postprocessing_ms": { "mean": 21.2, "p95": 25.2 },
      "total_ms": { "mean": 36.0, "p95": 40.1 }
    },
    "total_frames": 14200,
    "detections_count": 2
  },
  "detections": [
    {
      "class_id": 0,
      "class_name": "person",
      "confidence": 0.8845,
      "box": { "xmin": 0.245, "ymin": 0.120, "xmax": 0.450, "ymax": 0.680 }
    }
  ],
  "metrics": {
    "cpu_utilisation": { "value": 24.5, "unit": "percent", "status": "AVAILABLE" }
  }
}
```
