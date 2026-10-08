# Security Policy

## 1. Scope & Design Principles

**Edge Vision Monitor** is designed for deployment on edge Linux systems (such as the Raspberry Pi 5 with Hailo-8L AI HAT+). The system adheres to **least-privilege** and **secure-by-default** principles:

- **Loopback Binding by Default**: The API server binds to `127.0.0.1` unless explicitly configured to bind to a wider network interface (`0.0.0.0`).
- **No Arbitrary Command Execution**: No endpoint or subsystem accepts shell commands or arbitrary script execution.
- **Path Traversal Guards**: Prerecorded video selection is restricted to the validated `media_dir` directory.
- **Isolated Containers**: The Podman deployment uses explicit device nodes (`/dev/hailo0`, `/dev/video0`) and read-only mounts (`/sys/class/hwmon:ro`, `/sys/class/thermal:ro`) rather than `--privileged`.
- **Read-Only Models & Media**: Model binaries and media files are mounted read-only inside containers.
- **No Biometrics or Facial Recognition**: The inference pipeline strictly processes general object categories (e.g. COCO-80 classes). No facial recognition or identity tracking functionality is included.

---

## 2. Container & Host Permissions

When deploying via Podman or Docker:
1. Do not use `--privileged`.
2. Map only specific device nodes:
   - Hailo-8L: `/dev/hailo0`
   - USB Camera: `/dev/video0`
3. Keep host `/sys` mounts strictly read-only (`:ro`).
4. Mount persistent storage (`./data`) separately from application code.

---

## 3. Reporting a Vulnerability

If you identify a security vulnerability in this project, please report it privately:

- **Maintainer**: Mosud I. O.
- **Email**: `imosudi@gmail.com`
- **Response Window**: Security reports are acknowledged within 48 hours.

Please do not open public GitHub issues for security vulnerabilities until a patch has been published.
