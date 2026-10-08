# Physical Hardware Integration Tests

This test suite executes verification against physical edge hardware:
- **Raspberry Pi 5** (ARM64)
- **Hailo-8L AI HAT+** (`/dev/hailo0` via PCIe Gen2 / Gen3)
- **Raspberry Pi Camera Module** (CSI via Picamera2 / libcamera)
- **USB Webcam** (V4L2 `/dev/video*`)

---

## Running Physical Hardware Tests

On your configured Raspberry Pi 5 hardware host:

```bash
# Ensure user is in 'video' and 'i2c' groups
groups | grep -E 'video|i2c'

# Run hardware test suite
pytest tests/hardware/ -v -s
```

> [!NOTE]
> Tests will automatically skip with informative messages when executed on CI runners or developer machines lacking physical Hailo-8L PCIe hardware.
