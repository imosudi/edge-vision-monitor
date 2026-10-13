# YOLO11 Model Provisioning & Multi-Backend Guide

This directory holds model artefacts for **Edge Vision Monitor**, supporting both **Hailo-8L NPU hardware acceleration** and **CPU fallback/benchmarking via ONNX Runtime**.

> [!TIP]
> **Dedicated Training & Optimisation Suite:**
> An extensive and dedicated YOLO11 pipeline for dataset calibration, training, post-training quantisation (PTQ), and Hailo DFC compilation is available at:
> 🔗 **[https://github.com/imosudi/hailo-yolo11-compiler](https://github.com/imosudi/hailo-yolo11-compiler)**

---

## 1. Directory Structure

Place your model artefacts in the structured subdirectories:

```text
models/
├── hailo/
│   └── model.hef          # Compiled Hailo-8L executable (or symlinked to yolo11n.hef)
├── onnx/
│   └── model.onnx         # ONNX format model for CPU inference (float32 NCHW)
├── pytorch/
│   ├── best.pt            # PyTorch training checkpoint
│   └── best.onnx          # Raw PyTorch ONNX export
├── labels.txt             # Class label names (one per line, e.g. COCO 80 classes)
├── yolo11n.hef            # (Optional) Direct HEF path / symlink
└── README.md
```

---

## 2. Supported Inference Backends

| Backend | File Format | Engine / Library | Performance on Pi 5 |
| :--- | :--- | :--- | :--- |
| **Hailo-8L NPU** | `models/hailo/model.hef` | `hailo_platform` (PyHailoRT) | **~14 ms** (~27+ FPS) |
| **CPU Fallback** | `models/onnx/model.onnx` | `onnxruntime` (`CPUExecutionProvider`) | **~173 ms** (~5.5 FPS) |
| **Mock Engine** | Synthetic Data | Built-in test mock | For headless testing |

The active backend can be configured at startup or switched dynamically at runtime via the web UI or REST API (`POST /api/v1/inference/backend`).

---

## 3. Acquiring and Compiling Models

### Step 1: Export YOLO11 to ONNX
Export your trained model from PyTorch to ONNX format (opset 11 is recommended for Hailo DFC compatibility):

```bash
yolo export model=yolo11n.pt format=onnx opset=11
# Move to onnx directory for CPU runtime support
cp yolo11n.onnx models/onnx/model.onnx
```

### Step 2: Compile with Hailo Dataflow Compiler (DFC)
Compile the ONNX model into a quantised Hailo Executable Format (`.hef`) binary targeting the Hailo-8L:

```bash
hailo-yolo11-compiler compile \
    --onnx models/onnx/model.onnx \
    --target hailo8l \
    --calib-dataset /path/to/calib_images \
    --output models/hailo/model.hef
```

### Step 3: Verify HEF on Raspberry Pi 5
Validate network stream names and output nodes:

```bash
hailortcli parse-hef models/hailo/model.hef
```

---

## 4. Configuration Reference

Configure model paths and default backend in `config/config.yaml`:

```yaml
model:
  active_backend: "hailo"           # Default backend: "hailo" or "cpu"
  hef_path: "models/yolo11n.hef"    # Path to Hailo-8L HEF (or models/hailo/model.hef)
  onnx_path: "models/onnx/model.onnx" # Path to CPU ONNX model
  labels_path: "models/labels.txt"  # Class labels file
  confidence_threshold: 0.25
  nms_iou_threshold: 0.45
  max_detections: 100
```

Or using environment variables:

```bash
export EVM_MODEL__ACTIVE_BACKEND="hailo"
export EVM_MODEL__HEF_PATH="models/hailo/model.hef"
export EVM_MODEL__ONNX_PATH="models/onnx/model.onnx"
export EVM_MODEL__LABELS_PATH="models/labels.txt"
```
