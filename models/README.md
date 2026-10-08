# YOLO11 Hailo Model Provisioning Guide

This directory holds the compiled **Hailo Executable Format (`.hef`)** models, class labels, and metadata files.

> [!IMPORTANT]
> Do not place generic PyTorch (`.pt`) or ONNX (`.onnx`) files here. The Hailo-8L AI HAT+ executes hardware-quantized `.hef` binaries compiled with the Hailo Dataflow Compiler (DFC).

---

## 1. Acquiring or Compiling a YOLO11 HEF

You can compile a YOLO11 model (such as `yolo11n.pt` or `yolo11s.pt`) targeting the **Hailo-8L** using the Hailo Model Zoo or companion compilation workspace:

1. **Export to ONNX**:
   ```bash
   yolo export model=yolo11n.pt format=onnx opset=11
   ```

2. **Compile with Hailo DFC**:
   ```bash
   hailo-yolo11-compiler compile \
       --onnx yolo11n.onnx \
       --target hailo8l \
       --calib-dataset /path/to/calib_images \
       --output models/yolo11n.hef
   ```

3. **Verify HEF Integrity**:
   Run `hailortcli parse-hef models/yolo11n.hef` on your Raspberry Pi 5 to confirm network stream names and compatible output nodes.

---

## 2. Directory Layout

Place your artifacts in this directory as follows:

```text
models/
├── labels.txt          # One class name per line (e.g. COCO 80 classes)
├── model.yaml          # Optional class names or metadata mapping
├── yolo11n.hef         # Compiled Hailo-8L executable
└── README.md
```

---

## 3. Configuration Reference

In `config/config.yaml` or via environment variables, reference your model files:

```yaml
model:
  hef_path: "models/yolo11n.hef"
  labels_path: "models/labels.txt"
  metadata_path: null
  input_width: 640
  input_height: 640
  confidence_threshold: 0.25
  nms_iou_threshold: 0.45
```

Or using environment variables:
```bash
export EVM_MODEL__HEF_PATH="/opt/models/yolo11n.hef"
export EVM_MODEL__LABELS_PATH="/opt/models/labels.txt"
```
