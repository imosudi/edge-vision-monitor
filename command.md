# Edge Vision Monitor: Exhaustive Prompt Reference Tables

This document provides a comprehensive, exhaustive reference of all interactive prompts, submenus, CLI configuration flags, and project trajectory deliverables for the **Edge Vision Monitor** (Raspberry Pi 5 + Hailo-8L Edge AI & Telemetry Platform).

---

## 1. Main Interactive Deployment Menu Prompts (`main.py`)

When running `python main.py` or `python main.py --prompt` in an interactive terminal, the orchestrator triggers `prompt_deployment_menu()`:

| Selection Index | Prompt Label | Deployment Category | Target Execution / Handler |
| :---: | :--- | :--- | :--- |
| `[1]` | **Native On-Device Execution** | Bare-metal host execution | Starts Uvicorn + FastAPI + YOLO11 (Hailo/ONNX) + Telemetry via `run_native()`. |
| `[2]` | **Standalone Microservice Worker** | Single microservice process | Prompts for worker role (`ingress`, `inference`, `telemetry`, `storage`, `gateway`) and launches dedicated service. |
| `[3]` | **Monolithic Container Deployment** | Single unified container | Prompts for target host and Compose action for `compose.yaml`. |
| `[4]` | **Microservices Decomposition Deployment** | 5 segregated containers | Prompts for target host and Compose action for `compose.microservices.yaml`. |
| `[5]` | **systemd Host Service Management** | Linux init system daemon | Prompts for install, status, live journal logs, restart, or stop of host systemd unit. |
| `[6]` | **Pre-flight Hardware Diagnostics Check** | Silicon & sysfs verification | Executes `scripts/diagnose.py` to check PCIe `/dev/hailo0`, V4L2 nodes, and thermal sensors. |
| `[7]` | **Display Least-Privilege Comparison Matrix** | Architecture documentation | Renders the Least-Privilege Security & Hardware Access Matrix comparing Monolithic vs Microservices. |
| `[8]` | **Hailo-8L NPU Live Terminal Monitor** | Real-time terminal telemetry | Launches `scripts/hailo_monitor.py` dashboard showing NPU junction temp ($T_j$), load %, FPS, and latencies. |
| `[0]` | **Exit** | Termination | Cleanly exits the CLI application with exit code `0`. |

---

## 2. Remote Host Configuration Prompts (`prompt_remote_host_options`)

Prompted automatically when selecting choices `[1]`, `[2]`, `[3]`, `[4]`, `[5]`, `[6]`, or `[8]` in `prompt_remote_host_options()`:

| Step | Interactive Prompt String | Valid Inputs / Choices | Default Value | Internal Parameter |
| :---: | :--- | :--- | :--- | :--- |
| **2.1** | `Select deployment host for <Target>:` | `[1]` Local host<br>`[2]` Remote host | `1` (Local host) | `host_choice` |
| **2.2** | `Enter remote host IP address or hostname:` | IPv4, IPv6, or mDNS hostname (e.g. `10.79.67.118`, `iotgwai.local`) | `$EVM_REMOTE_HOST` or `10.236.235.118` | `remote_host` |
| **2.3** | `Enter privileged login user (e.g. root, docker-enabled user):` | Linux username (e.g. `iotgwai`, `root`) | `$EVM_REMOTE_USER` or `iotgwai` | `remote_user` |
| **2.4** | `Enter remote SSH port:` | Port number (`1`–`65535`) | `22` | `remote_port` |
| **2.5** | `Select SSH authentication method:` | `[1]` Password authentication<br>`[2]` SSH identity key / agent | `1` (Password) | `remote_auth` |
| **2.6** | `Enter SSH identity key file path:` *(only if auth=2)* | Path to private key file (e.g. `~/.ssh/id_rsa`) | Default SSH agent/keys | `remote_key` |
| **2.7** | `Enter remote project directory:` | Directory path on remote machine | `~/edge-vision-monitor` | `remote_dir` |

---

## 3. Submenu Action Prompts

### A. Standalone Microservice Worker Role Prompts (Menu `[2]`)

| Choice | Role Name | Primary Hardware / IPC Boundaries | CLI Flag |
| :---: | :--- | :--- | :--- |
| `[1]` | **Ingress** | Video capture from camera/files; writes raw frames to `/dev/shm` | `--service ingress` |
| `[2]` | **Inference** | Hailo-8L NPU PCIe accelerator `/dev/hailo0` & ONNX CPU engine | `--service inference` |
| `[3]` | **Telemetry** | Hardware sensor sysfs (`/sys/class/hwmon`), ambient ESP32 (`/dev/ttyUSB0`) | `--service telemetry` |
| `[4]` | **Storage** | SQLite WAL time-series database persistence (`data/telemetry.db`) | `--service storage` |
| `[5]` | **Gateway** | FastAPI REST & WebSocket server, MJPEG preview stream on port `8000` | `--service gateway` |

### B. Container Compose Action Prompts (Menus `[3]` & `[4]`)

| Choice | Compose Action | Execution Behavior | CLI Equivalent |
| :---: | :--- | :--- | :--- |
| `[1]` | **Start & display live monitor** *(Default)* | Launches containers in background and immediately attaches live Hailo-8L telemetry monitor | `compose up -d && hailo-monitor` |
| `[2]` | **Start in background only** | Launches containers detached without attaching terminal monitor | `compose up -d --no-monitor` |
| `[3]` | **Stop all containers** | Shuts down and removes running service containers | `compose down` |
| `[4]` | **View container logs** | Follows container stdout/stderr log output in real-time | `compose logs -f` |
| `[5]` | **Inspect container status** | Displays running containers, ports, uptime, and container health | `compose ps` |
| `[6]` | **Target specific microservice** *(Decomposition only)* | Prompts: `Enter microservice name [ingress/inference/telemetry/storage/gateway]` | `compose up <service>` |

### C. systemd Host Service Management Prompts (Menu `[5]`)

| Choice | Action Label | Systemd Operation Triggered | CLI Equivalent |
| :---: | :--- | :--- | :--- |
| `[1]` | **Inspect service status** *(Default)* | Queries active state, PID, memory, and latest journal entries | `systemctl status edge-vision-monitor` |
| `[2]` | **Install and enable service at boot** | Generates unit files in `/etc/systemd/system` and enables daemon | `systemctl enable --now edge-vision-monitor` |
| `[3]` | **View journal logs** | Streams live logs from systemd journal | `journalctl -u edge-vision-monitor -f` |
| `[4]` | **Restart service** | Restarts daemon unit | `systemctl restart edge-vision-monitor` |
| `[5]` | **Stop service** | Gracefully halts daemon unit | `systemctl stop edge-vision-monitor` |

---

## 4. CLI Argument Flags Matrix (`main.py`)

| Command / Scope | Flag | Registered Aliases | Type / Choices | Default | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Global** | `--prompt` | `-i`, `--interactive` | Flag | `False` | Forces interactive deployment prompt menu. |
| **Global** | `--no-prompt` | — | Flag | `False` | Suppresses prompt and executes default on-device native runner. |
| **Global** | `--mode` | — | `native`, `compose`, `microservices`, `systemd`, `diagnose` | `None` | Explicit deployment mode selection. |
| **Global** | `--remote-host` | `-H`, `--remote` | `str` | `$EVM_REMOTE_HOST` | Target remote host IP or hostname. |
| **Global** | `--remote-user` | `-u`, `--user` | `str` | `$EVM_REMOTE_USER` | Target remote privileged login user. |
| **Global** | `--remote-port` | — | `int` | `22` | Target remote SSH port. |
| **Global** | `--remote-auth` | — | `password`, `key` | `password` | SSH authentication mechanism. |
| **Global** | `--remote-key` | `-k` | Path (`str`) | `None` | Path to private SSH key. |
| **Global** | `--remote-dir` | — | Path (`str`) | `~/edge-vision-monitor` | Working repository root on remote host. |
| `compose` | `--microservices` | `-m` | Flag | `False` | Target 5-container `compose.microservices.yaml`. |
| `compose` | `--detach` | `-d` | Flag | `True` | Run containers in detached background mode. |
| `compose` | `--monitor` | — | Flag | `True` on `up` | Attach live Hailo-8L monitor after starting containers. |
| `compose` | `--no-monitor` | — | Flag | `False` | Do not launch monitor after container startup. |
| `run` | `--service` | — | `all`, `ingress`, `inference`, `telemetry`, `storage`, `gateway` | `all` | Specific microservice worker role to execute natively. |
| `run` | `--host` | — | `str` | `0.0.0.0` | Binding interface for HTTP and WebSockets. |
| `run` | `--port` | — | `int` | `8000` | Port for HTTP and WebSockets. |
| `benchmark` | `--workload` | `-w` | `A`, `B`, `C`, `D` | `A` | Target Hailo-8L stress workload profile. |
| `benchmark` | `--streams` | — | `1`, `2`, `4`, `6`, `8`, `12`, `16`, `20` | `4` | Number of concurrent ingestion stream channels for Workloads B, C, and D. |
| `benchmark` | `--duration` | `-d` | `float` | `60.0` | Target workload duration in seconds. |
| `benchmark` | `--target-temp` | `-t` | `float` | `100.0` | Target junction temperature ($T_j$) in °C for Workloads C and D. |
| `benchmark` | `--safety-limit` | `-s` | `float` | `102.0` | Automated emergency shutdown safety temperature limit in °C. |
| `benchmark` | `--simulate` | — | Flag | `False` | Run in thermal simulation mode for software & hysteresis testing. |
| `benchmark` | `--buffer-size` | — | `int` | `120` | Preloaded RAM frame buffer size for high-throughput Workload A. |
| `benchmark` | `--file` | — | Path (`str`) | `None` | Custom video media file path to preload for concurrent streaming. |
| `benchmark` | `--output` | `-o` | Path (`str`) | `None` | Output file path to export time-series trajectory upon completion. |
| `benchmark` | `--format` | — | `csv`, `json` | `csv` | Export format for recorded telemetry trajectory. |

---

## 5. Project User Prompts & Deliverables History

Exhaustive record of all task prompts requested across this project trajectory:

| # | User Request / Directive | Target Subsystem | Deliverable Achieved |
| :---: | :--- | :--- | :--- |
| **1** | *"git commit the all models/hailo models/onnx/ models/pytorch/"* | Model Artifacts | Tracked and committed Hailo HEF, ONNX, and PyTorch model files and symlinks (`models/yolo11n.hef`, `models/yolo11n.onnx`). |
| **2** | *"The first image is the current view of the button, the second view is the expected button view"* | Web UI Navbar | Restored the top navigation layout with segmented Hailo/CPU switcher and standalone action buttons. |
| **3** | *"Menu view"* | CLI Orchestrator | Implemented interactive menu prompt hierarchy in `main.py`. |
| **4** | *"Hailo-8L, CPU (ONNX), and Dual Benchmark are not all expected to be disabled..."* | Frontend JavaScript | Updated `app/static/js/app.js` so inference buttons remain clickable without locking the UI. |
| **5** | *"CPU (ONNX) and Dual Benchmark buttons only disabled during their own inference..."* | Frontend JavaScript | Synchronized contextual workload button state management to isolate execution flags. |
| **6** | *"Hailo-8L button should be active by default running inference"* | Web UI & Core Engine | Initialized default active backend to Hailo-8L with highlighted active pill in navbar. |
| **7** | *"Click on the start button not running inference"* | Inference API & JS | Connected `toggleInference()` to `/api/v1/inference/start` and `/api/v1/inference/stop` with automatic timer management. |
| **8** | *"Start running YOLO11n (models/yolo11n.hef) NPU object identification model on project startup"* | Lifecycle & Engine | Configured automatic inference launch on boot in `app/core/lifecycle.py` and self-healing engine retry loops. |
| **9** | *"These were the sample screenshots from CLI and web interface, improve up project to achieve deliverables"* | CLI & Web Dashboard | Fully aligned CLI terminal monitor and Web Dashboard cards, HUD, latencies, and badges with reference screenshots. |
| **10** | *"main.py: error: ambiguous option: --remote"* | CLI Argument Parser | Added explicit `--remote` and `--user` aliases across all parsers in `main.py`. |
| **11** | *"NameError: name 'os' is not defined & sqlite3.OperationalError"* | Container Runtime | Added missing `os`/`glob` imports, resilient database fallback, and `1777`/`777` permission fixes for `/tmp/hmon_files` and `data/`. |
| **12** | *"Create untracked markdown file named command.md for the Exhaustive Prompt Reference Tables"* | Documentation | Created standalone untracked `command.md` containing all prompt reference tables. |
| **13** | *"git commit 'Concurrent Streams updated'"* | Repository & Documentation | Documented concurrent streams parameters in `command.md` and committed to git branch. |
