#!/usr/bin/env python3
"""
Edge Vision Monitor - Main Application Entry Point & Deployment Manager.

Unified orchestration interface for:
  1. On-Device Native Deployment: Direct Python/FastAPI/Uvicorn execution.
  2. Podman Compose Deployment: Rootless, least-privilege containerisation.
  3. systemd Integration: Host service generation, installation, and lifecycle management.
"""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

# Base project directory
PROJECT_ROOT = Path(__file__).resolve().parent
SYSTEMD_SERVICE_NAME = "edge-vision-monitor.service"
SYSTEMD_SERVICE_PATH = Path("/etc/systemd/system") / SYSTEMD_SERVICE_NAME

# Service name aliases for microservices decomposition
SERVICE_NAME_ALIASES = {
    "ingress": "edge-vision-ingress",
    "inference": "edge-vision-inference",
    "telemetry": "edge-vision-telemetry",
    "storage": "edge-vision-storage",
    "gateway": "edge-vision-gateway",
}


# ==============================================================================
# Helper / Terminal Formatting Utilities
# ==============================================================================

def _colourise(text: str, colour_code: str) -> str:
    if sys.stdout.isatty():
        return f"\033[{colour_code}m{text}\033[0m"
    return text


def log_info(msg: str):
    print(f"{_colourise('[INFO]', '32;1')} {msg}")


def log_warn(msg: str):
    print(f"{_colourise('[WARN]', '33;1')} {msg}")


def log_error(msg: str):
    print(f"{_colourise('[ERROR]', '31;1')} {msg}", file=sys.stderr)


def log_step(title: str):
    print(f"\n{_colourise('===>', '36;1')} {_colourise(title, '1')}")


def print_banner():
    banner = r"""
  ______    _              __      ___     _               __  __             _ _             
 |  ____|  | |             \ \    / (_)   (_)             |  \/  |           (_) |            
 | |__   __| | __ _  ___    \ \  / / _ ___ _  ___  _ __   | \  / | ___  _ __  _| |_ ___  _ __ 
 |  __| / _` |/ _` |/ _ \    \ \/ / | / __| |/ _ \| '_ \  | |\/| |/ _ \| '_ \| | __/ _ \| '__|
 | |___| (_| | (_| |  __/     \  /  | \__ \ | (_) | | | | | |  | | (_) | | | | | || (_) | |   
 |______\__,_|\__, |\___|      \/   |_|___/_|\___/|_| |_| |_|  |_|\___/|_| |_|_|\__\___/|_|   
               __/ |                                                                          
              |___/      Raspberry Pi 5 + Hailo-8L Edge AI & Telemetry Platform
"""
    print(_colourise(banner, "36"))


def print_service_matrix():
    """Display the Least-Privilege Service Comparison Matrix and deployment options."""
    log_step("Service Comparison Matrix & Microservices Decomposition")
    print(f"\n{_colourise('=' * 104, '36')}")
    print(_colourise("               EDGE VISION MONITOR: LEAST-PRIVILEGE SERVICE COMPARISON MATRIX", "1;36"))
    print(_colourise("=" * 104, "36"))
    print(f"{_colourise('Service Name', '1;37'):<24} {_colourise('Hardware Devices', '1;37'):<22} {_colourise('Volume Mounts', '1;37'):<25} {_colourise('Network / IPC Segregation', '1;37'):<30}")
    print("-" * 104)

    matrix = [
        (
            "edge-vision-ingress",
            "Video Ingestion",
            "/dev/video*\n/dev/media*",
            "./media:/app/media:ro,Z\n/dev/shm:/dev/shm",
            "Zero-Copy IPC (/dev/shm)\nIsolation: V4L2 lock-ups do not crash UI",
            "34",
        ),
        (
            "edge-vision-inference",
            "YOLO11 NPU/CPU",
            "/dev/hailo0",
            "./models:/app/models:ro,Z\n/dev/shm:/dev/shm",
            "Zero-Copy IPC (/dev/shm)\nIsolation: NPU errors do not halt metrics",
            "35",
        ),
        (
            "edge-vision-telemetry",
            "Sensors & Metrics",
            "None (sysfs only)",
            "/sys/class/hwmon:ro\n/sys/class/thermal:ro\n./data:/app/data:Z",
            "Internal PubSub Bus\nIsolation: Sysfs I/O stalls do not drop video",
            "32",
        ),
        (
            "edge-vision-storage",
            "SQLite WAL DB",
            "None (Storage only)",
            "./data:/app/data:Z",
            "Internal SQL / RPC Endpoint\nIsolation: Disk writes do not cause jitter",
            "33",
        ),
        (
            "edge-vision-gateway",
            "Web UI & FastAPIs",
            "None (Unprivileged)",
            "None (Stateless)\n/dev/shm:ro",
            "Port 8000:8000 (HTTP / WS)\nIsolation: Web exploits cannot access nodes",
            "31",
        ),
    ]

    for name, role, devs, vols, net, colour in matrix:
        name_str = _colourise(f"{name}", f"1;{colour}")
        role_str = _colourise(f"({role})", "90")
        print(f"{name_str:<33} {role_str}")

        dev_lines = devs.split("\n")
        vol_lines = vols.split("\n")
        net_lines = net.split("\n")
        max_sub = max(len(dev_lines), len(vol_lines), len(net_lines))
        for i in range(max_sub):
            d = dev_lines[i] if i < len(dev_lines) else ""
            v = vol_lines[i] if i < len(vol_lines) else ""
            n = net_lines[i] if i < len(net_lines) else ""
            print(f"  {d:<22} {v:<27} {n}")
        print("-" * 104)

    print(f"\n{_colourise('Container Service Deployment Options:', '1;36')}")
    print(f"  {_colourise('1. Monolithic Container (compose.yaml):', '1')} Single unified container (~195 MB RSS), simple orchestration.")
    print(f"     Command: {_colourise('python main.py compose up -d', '32')}")
    print(f"  {_colourise('2. Microservices Decomposition (compose.microservices.yaml):', '1')} 5 decomposed least-privilege containers (~260-290 MB RSS), isolated failure domains, zero-copy /dev/shm IPC.")
    print(f"     Command: {_colourise('python main.py compose --microservices up -d', '32')}")
    print(f"     Target:  {_colourise('python main.py compose up -m ingress', '32')} (or inference, telemetry, storage, gateway)\n")


# ==============================================================================
# 1. On-Device Native Deployment
# ==============================================================================

def run_native(args: argparse.Namespace) -> int:
    """Start Edge Vision Monitor natively using Uvicorn or dedicated microservice worker."""
    log_step("Starting On-Device Native Deployment")

    # Set custom config file path if specified
    if getattr(args, "config", None):
        cfg_path = Path(args.config).resolve()
        if not cfg_path.exists():
            log_error(f"Config file not found: {cfg_path}")
            return 1
        os.environ["EVM_CONFIG_PATH"] = str(cfg_path)
        log_info(f"Using configuration file: {cfg_path}")

    service_mode = (getattr(args, "service", None) or os.getenv("EVM_SERVICE", "all")).lower()
    os.environ["EVM_SERVICE"] = service_mode

    # Run optional hardware diagnostics first
    if getattr(args, "diagnose", False):
        log_step("Running Pre-flight Hardware Diagnostics")
        try:
            from scripts.diagnose import main as run_diagnostics
            run_diagnostics()
        except ImportError:
            log_warn("Diagnostic script 'scripts.diagnose' could not be imported. Skipping diagnostics.")

    # If a standalone non-web microservice worker is requested, launch worker loop directly
    if service_mode in ("ingress", "inference", "telemetry", "storage"):
        log_step(f"Starting Standalone Microservice Worker: {service_mode.upper()}")
        from app.core.lifecycle import run_service_worker
        return run_service_worker(service_mode)

    # Load configuration
    try:
        from app.core.config import load_config
        config = load_config()
    except Exception as exc:
        log_warn(f"Could not load application configuration dynamically ({exc}). Falling back to CLI arguments/defaults.")
        config = None

    host = getattr(args, "host", None) or (config.server.host if config else "0.0.0.0")
    port = getattr(args, "port", None) or (config.server.port if config else 8000)
    reload = getattr(args, "reload", False)
    workers = getattr(args, "workers", 1)
    log_level = (getattr(args, "log_level", None) or (config.server.log_level if config else "INFO")).lower()

    log_info(f"Subsystem Role:    {service_mode.upper()}")
    log_info(f"Target Host:       {host}")
    log_info(f"Target Port:       {port}")
    log_info(f"Log Level:         {log_level.upper()}")
    log_info(f"Auto-Reload:       {reload}")
    log_info(f"Process PID:       {os.getpid()}")
    log_info(f"Dashboard URL:     http://{host if host != '0.0.0.0' else 'localhost'}:{port}")

    try:
        import uvicorn
        uvicorn.run(
            "app.main:app",
            host=host,
            port=int(port),
            reload=reload,
            workers=int(workers) if not reload else 1,
            log_level=log_level,
            access_log=False,
        )
        return 0
    except KeyboardInterrupt:
        log_info("Received interrupt signal (Ctrl+C). Shutting down cleanly.")
        return 0
    except Exception as exc:
        log_error(f"Failed to start Uvicorn server: {exc}")
        return 1


# ==============================================================================
# 2. Podman / Container Compose Deployment
# ==============================================================================

def find_compose_command(preferred_engine: Optional[str] = None) -> Optional[List[str]]:
    """
    Locate the appropriate compose command in order of preference:
      1. podman compose
      2. podman-compose
      3. docker compose
      4. docker-compose
    """
    candidates = []
    if preferred_engine == "podman":
        candidates = [
            ["podman", "compose"],
            ["podman-compose"],
        ]
    elif preferred_engine == "docker":
        candidates = [
            ["docker", "compose"],
            ["docker-compose"],
        ]
    else:
        candidates = [
            ["podman", "compose"],
            ["podman-compose"],
            ["docker", "compose"],
            ["docker-compose"],
        ]

    for cmd in candidates:
        prog = cmd[0]
        if shutil.which(prog) is None:
            continue
        try:
            # Check if subcommand works (e.g. 'podman compose --help' or 'docker compose version')
            test_args = cmd + ["version"] if len(cmd) > 1 else [cmd[0], "--version"]
            res = subprocess.run(test_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if res.returncode == 0:
                return cmd
        except Exception:
            continue

    # Fallback check for single binary without version test failure
    for cmd in candidates:
        if shutil.which(cmd[0]):
            return cmd

    return None


def run_compose(args: argparse.Namespace) -> int:
    """Manage Podman/Docker Compose deployment (Monolithic or Microservices Decomposition)."""
    # Check for matrix or services review action first
    action = getattr(args, "compose_action", None) or "up"
    if action in ("matrix", "services"):
        print_service_matrix()
        return 0

    log_step("Managing Container Compose Deployment")

    # Determine architecture deployment option (Monolithic vs Microservices)
    is_microservices = getattr(args, "microservices", False) or getattr(args, "type", None) == "microservices"
    custom_file = getattr(args, "file", None)

    if custom_file:
        compose_file = Path(custom_file).resolve()
    elif is_microservices:
        compose_file = (PROJECT_ROOT / "compose.microservices.yaml").resolve()
    else:
        compose_file = (PROJECT_ROOT / "compose.yaml").resolve()

    if not compose_file.exists():
        log_error(f"Compose file does not exist: {compose_file}")
        return 1

    engine_pref = getattr(args, "engine", None)
    compose_cmd = find_compose_command(engine_pref)

    if not compose_cmd:
        log_error("Neither 'podman compose', 'podman-compose', nor 'docker compose' was found on this system.")
        print("\nTo install Podman on Debian/Raspberry Pi OS:")
        print("    sudo apt update && sudo apt install -y podman podman-compose\n")
        return 1

    engine_name = " ".join(compose_cmd)
    arch_type = "Microservices Decomposition" if is_microservices else "Monolithic Container"
    log_info(f"Deployment Architecture:   {_colourise(arch_type, '36;1')}")
    log_info(f"Detected container engine: {_colourise(engine_name, '32')}")
    log_info(f"Using compose file:        {compose_file}")

    remote_host = getattr(args, "remote_host", None)
    remote_user = getattr(args, "remote_user", None)
    remote_port = getattr(args, "remote_port", None) or 22
    remote_key = getattr(args, "remote_key", None)
    remote_dir = getattr(args, "remote_dir", None) or "~/edge-vision-monitor"
    remote_method = getattr(args, "remote_method", "ssh")

    # If remote_host was passed as user@host or host:port, normalise
    if remote_host:
        clean_host = remote_host.strip()
        if clean_host.startswith("ssh://"):
            clean_host = clean_host[6:]
        elif clean_host.startswith("tcp://"):
            clean_host = clean_host[6:]
        if "@" in clean_host:
            parsed_user, clean_host = clean_host.split("@", 1)
            remote_user = remote_user or parsed_user
        if ":" in clean_host:
            clean_host, parsed_port = clean_host.split(":", 1)
            if parsed_port.isdigit():
                remote_port = int(parsed_port)
        remote_host = clean_host

    if remote_host:
        log_info(f"Target Remote Host:        {_colourise(remote_host, '35;1')}")
        if remote_user:
            log_info(f"Privileged Login User:     {_colourise(remote_user, '33;1')}")
        log_info(f"Remote SSH Port:           {remote_port}")
        log_info(f"Remote Project Directory:  {remote_dir}")
        log_info("Hardware node verification (/dev/hailo0, /dev/video0) deferred to remote host environment.")
    else:
        log_info("Deployment Target:         Local Host")
        # Check hardware nodes on local host
        if not Path("/dev/hailo0").exists():
            log_warn("Hardware node /dev/hailo0 not detected on host. Container inference will operate in Mock/CPU mode.")
        if not Path("/dev/video0").exists():
            log_warn("Video device /dev/video0 not detected on host. Video file playback will be required.")

    # Build compose action arguments
    action_args: List[str] = []
    if action == "up":
        action_args.append("up")
        if not getattr(args, "no_detach", False):
            action_args.append("-d")
        if getattr(args, "build", False):
            action_args.append("--build")
    elif action == "down":
        action_args.append("down")
        if getattr(args, "volumes", False):
            action_args.append("-v")
    elif action == "restart":
        action_args.append("restart")
    elif action == "build":
        action_args.append("build")
        if getattr(args, "no_cache", False):
            action_args.append("--no-cache")
    elif action == "logs":
        action_args.append("logs")
        if getattr(args, "follow", True):
            action_args.append("-f")
        if getattr(args, "tail", None):
            action_args.extend(["--tail", str(args.tail)])
    elif action in ("ps", "status"):
        action_args.append("ps")
    else:
        action_args.append(action)

    # Append any targeted service names
    target_services = getattr(args, "services", []) or []
    if target_services:
        mapped_targets = []
        for s in target_services:
            mapped_targets.append(SERVICE_NAME_ALIASES.get(s, s) if is_microservices else s)
        action_args.extend(mapped_targets)

    env = os.environ.copy()

    # Route 1: Direct SSH execution to remote edge host
    if remote_host and remote_method == "ssh" and shutil.which("ssh"):
        compose_filename = "compose.microservices.yaml" if is_microservices else "compose.yaml"
        action_str = " ".join(action_args)
        remote_exec = f"cd {remote_dir} && (podman compose -f {compose_filename} {action_str} 2>/dev/null || docker compose -f {compose_filename} {action_str})"

        cmd = ["ssh"]
        if sys.stdin.isatty():
            cmd.append("-t")

        # Prevent host verification stalls and agent key flooding ('Too many authentication failures')
        cmd.extend(["-o", "StrictHostKeyChecking=accept-new"])
        remote_auth = getattr(args, "remote_auth", None)
        if remote_auth == "password" or (not remote_key and remote_auth != "key"):
            cmd.extend([
                "-o", "PubkeyAuthentication=no",
                "-o", "PreferredAuthentications=password,keyboard-interactive",
            ])
        else:
            if remote_key:
                cmd.extend(["-i", str(remote_key), "-o", "IdentitiesOnly=yes"])
            else:
                cmd.extend(["-o", "PubkeyAuthentication=yes"])

        if remote_port and str(remote_port) != "22":
            cmd.extend(["-p", str(remote_port)])

        login_target = f"{remote_user}@{remote_host}" if remote_user else remote_host
        cmd.extend([login_target, remote_exec])

    # Route 2: Local container engine or remote daemon socket connection
    else:
        cmd = list(compose_cmd)
        if remote_host:
            login_target = f"{remote_user}@{remote_host}" if remote_user else remote_host
            endpoint = f"ssh://{login_target}:{remote_port}" if (remote_port and str(remote_port) != "22") else f"ssh://{login_target}"
            if cmd[0] == "docker":
                cmd[1:1] = ["-H", endpoint]
            elif cmd[0] == "podman" and len(cmd) > 1 and cmd[1] == "compose":
                cmd[1:1] = ["--url", endpoint]
            env["DOCKER_HOST"] = endpoint
            env["CONTAINER_HOST"] = endpoint

        cmd.extend(["-f", str(compose_file)])
        cmd.extend(action_args)

    log_info(f"Executing: {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env)
        return proc.returncode
    except KeyboardInterrupt:
        log_info("Execution interrupted by user.")
        return 0
    except Exception as exc:
        log_error(f"Failed to execute compose command: {exc}")
        return 1


# ==============================================================================
# 3. systemd Service Integration
# ==============================================================================

def get_python_executable(workdir: Path) -> Path:
    """Return the preferred Python executable, preserving virtual environments."""
    # 1. Check if running inside an active virtualenv
    if sys.prefix != sys.base_prefix:
        return Path(sys.executable).absolute()

    # 2. Check if a .venv directory exists in project root
    local_venv_py = workdir / ".venv" / "bin" / "python"
    if local_venv_py.exists():
        return local_venv_py.absolute()

    # 3. Fallback to current sys.executable
    return Path(sys.executable).absolute()


def generate_systemd_unit(
    user: str,
    group: str,
    workdir: Path,
    python_bin: Path,
    config_path: Path,
    host: str = "0.0.0.0",
    port: int = 8000,
) -> str:
    """Generate production systemd unit file content."""
    venv_bin_dir = python_bin.parent
    return f"""[Unit]
Description=Edge Vision Monitor Platform
After=network.target local-fs.target
Wants=network-online.target

[Service]
Type=simple
User={user}
Group={group}
WorkingDirectory={workdir}
Environment="PATH={venv_bin_dir}:/usr/local/bin:/usr/bin"
Environment="EVM_CONFIG_PATH={config_path}"
Environment="EVM_SERVER__HOST={host}"
Environment="EVM_SERVER__PORT={port}"
ExecStart={python_bin} {workdir}/main.py run --host {host} --port {port}
Restart=always
RestartSec=3s
TimeoutStopSec=10s
KillSignal=SIGTERM

# Hardening & Write permissions
ProtectSystem=full
ReadWritePaths={workdir}

[Install]
WantedBy=multi-user.target
"""


def _run_systemctl(args_list: List[str]) -> subprocess.CompletedProcess:
    """Run systemctl command, prefixing with sudo if unprivileged."""
    cmd = ["systemctl"] + args_list
    if os.geteuid() != 0 and shutil.which("sudo"):
        cmd = ["sudo"] + cmd
    return subprocess.run(cmd, capture_output=True, text=True)


def run_systemd(args: argparse.Namespace) -> int:
    """Manage systemd integration for Edge Vision Monitor."""
    log_step("Managing systemd Service Integration")

    if shutil.which("systemctl") is None:
        log_error("systemctl not found on this system. systemd mode is only available on Linux with systemd.")
        return 1

    action = getattr(args, "systemd_action", None) or "status"

    if action in ("generate", "show"):
        default_user = os.environ.get("SUDO_USER") or getpass.getuser()
        user = getattr(args, "user", None) or default_user
        group = getattr(args, "group", None) or "video"
        workdir = PROJECT_ROOT
        custom_py = getattr(args, "python", None)
        python_bin = Path(custom_py).absolute() if custom_py else get_python_executable(workdir)
        config_path = PROJECT_ROOT / "config" / "config.yaml"
        host = getattr(args, "host", "0.0.0.0")
        port = getattr(args, "port", 8000)

        unit_content = generate_systemd_unit(user, group, workdir, python_bin, config_path, host, port)
        print(f"\n{_colourise('--- Generated systemd Service Configuration ---', '36')}")
        print(unit_content)
        print(_colourise("--------------------------------------------------", "36"))
        return 0

    if action == "install":
        log_info(f"Target service file: {SYSTEMD_SERVICE_PATH}")
        default_user = os.environ.get("SUDO_USER") or getpass.getuser()
        user = getattr(args, "user", None) or default_user
        group = getattr(args, "group", None) or "video"
        workdir = PROJECT_ROOT
        custom_py = getattr(args, "python", None)
        python_bin = Path(custom_py).absolute() if custom_py else get_python_executable(workdir)
        config_path = (PROJECT_ROOT / "config" / "config.yaml").resolve()
        host = getattr(args, "host", "0.0.0.0")
        port = getattr(args, "port", 8000)

        log_info(f"Service User:       {user}")
        log_info(f"Service Group:      {group}")
        log_info(f"Working Directory:  {workdir}")
        log_info(f"Python Executable:  {python_bin}")

        unit_content = generate_systemd_unit(user, group, workdir, python_bin, config_path, host, port)

        temp_file = PROJECT_ROOT / ".edge-vision-monitor.service.tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(unit_content)

            # Move unit file to /etc/systemd/system/
            cp_cmd = ["cp", str(temp_file), str(SYSTEMD_SERVICE_PATH)]
            if os.geteuid() != 0:
                cp_cmd = ["sudo"] + cp_cmd

            res = subprocess.run(cp_cmd, capture_output=True, text=True)
            if res.returncode != 0:
                log_error(f"Failed to copy service unit to {SYSTEMD_SERVICE_PATH}: {res.stderr}")
                return res.returncode

            # Reload systemd daemon
            reload_res = _run_systemctl(["daemon-reload"])
            if reload_res.returncode != 0:
                log_error(f"Failed to reload systemd daemon: {reload_res.stderr}")
                return reload_res.returncode
            log_info("systemd daemon reloaded successfully.")

            # Enable service if requested
            if not getattr(args, "no_enable", False):
                en_res = _run_systemctl(["enable", SYSTEMD_SERVICE_NAME])
                if en_res.returncode == 0:
                    log_info(f"Service '{SYSTEMD_SERVICE_NAME}' enabled at boot.")
                else:
                    log_warn(f"Failed to enable service: {en_res.stderr}")

            # Start service if requested
            if getattr(args, "start_now", False):
                start_res = _run_systemctl(["start", SYSTEMD_SERVICE_NAME])
                if start_res.returncode == 0:
                    log_info(f"Service '{SYSTEMD_SERVICE_NAME}' started.")
                else:
                    log_error(f"Failed to start service: {start_res.stderr}")
                    return start_res.returncode

            log_info("systemd installation complete!")
            print(f"\nUseful systemd commands:")
            print(f"  python main.py systemd status")
            print(f"  python main.py systemd logs")
            print(f"  python main.py systemd restart")
            print(f"  python main.py systemd stop\n")
            return 0
        finally:
            if temp_file.exists():
                temp_file.unlink(missing_ok=True)

    elif action == "uninstall":
        log_info(f"Uninstalling {SYSTEMD_SERVICE_NAME}...")
        _run_systemctl(["stop", SYSTEMD_SERVICE_NAME])
        _run_systemctl(["disable", SYSTEMD_SERVICE_NAME])
        rm_cmd = ["rm", "-f", str(SYSTEMD_SERVICE_PATH)]
        if os.geteuid() != 0:
            rm_cmd = ["sudo"] + rm_cmd
        subprocess.run(rm_cmd, check=False)
        _run_systemctl(["daemon-reload"])
        log_info(f"Service {SYSTEMD_SERVICE_NAME} removed and daemon reloaded.")
        return 0

    elif action in ("start", "stop", "restart"):
        log_info(f"Executing systemctl {action} {SYSTEMD_SERVICE_NAME}...")
        res = _run_systemctl([action, SYSTEMD_SERVICE_NAME])
        if res.returncode != 0:
            log_error(f"systemctl {action} failed: {res.stderr}")
            return res.returncode
        log_info(f"Service {SYSTEMD_SERVICE_NAME} {action}ed successfully.")
        return 0

    elif action == "status":
        res = subprocess.run(["systemctl", "status", SYSTEMD_SERVICE_NAME, "--no-pager"])
        return res.returncode

    elif action == "logs":
        lines = getattr(args, "lines", 50)
        cmd = ["journalctl", "-u", SYSTEMD_SERVICE_NAME, "-f", "-n", str(lines)]
        if os.geteuid() != 0 and shutil.which("sudo"):
            cmd = ["sudo"] + cmd
        try:
            return subprocess.run(cmd).returncode
        except KeyboardInterrupt:
            return 0

    else:
        log_error(f"Unknown systemd action: {action}")
        return 1


# ==============================================================================
# 4. Interactive Deployment Selection Prompt
# ==============================================================================

def prompt_deployment_menu(args: argparse.Namespace) -> int:
    """Prompt the user with an interactive deployment selection menu."""
    log_step("Interactive Deployment Selection")
    print("\nPlease choose an execution or deployment option:\n")
    print(f"  {_colourise('[1]', '36;1')} Native On-Device Execution (Uvicorn + FastAPI + Hailo/ONNX + Telemetry)")
    print(f"  {_colourise('[2]', '36;1')} Standalone Microservice Worker (Ingress, Inference, Telemetry, Storage, or Gateway)")
    print(f"  {_colourise('[3]', '36;1')} Monolithic Container Deployment (compose.yaml, single unified container)")
    print(f"  {_colourise('[4]', '36;1')} Microservices Decomposition Deployment (compose.microservices.yaml, 5 containers)")
    print(f"  {_colourise('[5]', '36;1')} systemd Host Service Management (Install, Status, Logs, Restart)")
    print(f"  {_colourise('[6]', '36;1')} Pre-flight Hardware Diagnostics Check (Hailo PCIe, V4L2, sysfs)")
    print(f"  {_colourise('[7]', '36;1')} Display Least-Privilege Service Comparison Matrix")
    print(f"  {_colourise('[0]', '31;1')} Exit\n")

    try:
        choice = input(_colourise("Enter selection [1-7, 0 to exit] (default: 1): ", "1;33")).strip()
    except (KeyboardInterrupt, EOFError):
        print("\nOperation cancelled.")
        return 0

    if not choice:
        choice = "1"

    if choice == "1":
        # Native On-Device Execution
        args.command = "run"
        args.service = getattr(args, "service", "all") or "all"
        return run_native(args)

    elif choice == "2":
        # Standalone Microservice Worker
        print("\nSelect standalone microservice role:")
        print("  [1] Ingress (Video capture and ingestion)")
        print("  [2] Inference (YOLO11 Hailo NPU / CPU ONNX engine)")
        print("  [3] Telemetry (Hardware sensors and metrics collector)")
        print("  [4] Storage (SQLite WAL time-series persistence)")
        print("  [5] Gateway (FastAPI server, WebSockets, preview stream)")
        try:
            sub = input(_colourise("Enter role [1-5] (default: 1): ", "1;33")).strip() or "1"
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            return 0
        roles = {"1": "ingress", "2": "inference", "3": "telemetry", "4": "storage", "5": "gateway"}
        args.command = "run"
        args.service = roles.get(sub, "all")
        return run_native(args)

    elif choice == "3":
        # Monolithic Container Deployment
        print("\nSelect Compose action for Monolithic Container:")
        print("  [1] Start container in background (up -d) [default]")
        print("  [2] Stop container (down)")
        print("  [3] View container logs (logs -f)")
        print("  [4] Inspect container status (ps)")
        try:
            act_choice = input(_colourise("Enter action [1-4] (default: 1): ", "1;33")).strip() or "1"
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            return 0
        act_map = {"1": "up", "2": "down", "3": "logs", "4": "ps"}
        args.command = "compose"
        args.compose_action = act_map.get(act_choice, "up")
        args.microservices = False
        args.type = "monolith"
        return run_compose(args)

    elif choice == "4":
        # Microservices Decomposition Deployment
        print("\nSelect deployment host for Microservices Decomposition:")
        print("  [1] Local host [default]")
        print("  [2] Remote host")
        try:
            host_choice = input(_colourise("Enter choice [1-2] (default: 1): ", "1;33")).strip() or "1"
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            return 0

        remote_host = None
        remote_user = None
        remote_port = 22
        remote_auth = "password"
        remote_key = None
        remote_dir = "~/edge-vision-monitor"

        if host_choice == "2":
            print()
            try:
                host_input = input(_colourise("Enter remote host IP address or hostname: ", "1;33")).strip()
            except (KeyboardInterrupt, EOFError):
                print("\nOperation cancelled.")
                return 0
            if not host_input:
                log_error("Remote host IP address or hostname is required.")
                return 1

            parsed_user = None
            parsed_port = None
            if "@" in host_input:
                parsed_user, host_input = host_input.split("@", 1)
            if ":" in host_input:
                host_input, port_str = host_input.split(":", 1)
                if port_str.isdigit():
                    parsed_port = int(port_str)

            remote_host = host_input
            default_user = parsed_user or os.getenv("USER") or "root"

            try:
                user_prompt = f"Enter privileged login user (e.g. root, docker-enabled user) [default: {default_user}]: "
                user_input = input(_colourise(user_prompt, "1;33")).strip()
                remote_user = user_input or default_user

                default_port = str(parsed_port or 22)
                port_prompt = f"Enter remote SSH port [default: {default_port}]: "
                port_input = input(_colourise(port_prompt, "1;33")).strip()
                remote_port = int(port_input) if (port_input and port_input.isdigit()) else int(default_port)

                print("Select SSH authentication method:")
                print("  [1] Password authentication [default]")
                print("  [2] SSH identity key / agent")
                auth_choice = input(_colourise("Enter choice [1-2] (default: 1): ", "1;33")).strip() or "1"
                if auth_choice == "2":
                    remote_auth = "key"
                    key_prompt = "Enter SSH identity key file path (optional, press Enter for default agent/keys): "
                    key_input = input(_colourise(key_prompt, "1;33")).strip()
                    remote_key = key_input or None
                else:
                    remote_auth = "password"
                    remote_key = None

                dir_prompt = "Enter remote project directory [default: ~/edge-vision-monitor]: "
                dir_input = input(_colourise(dir_prompt, "1;33")).strip()
                remote_dir = dir_input or "~/edge-vision-monitor"
            except (KeyboardInterrupt, EOFError):
                print("\nOperation cancelled.")
                return 0

        print("\nSelect Compose action for Microservices Decomposition:")
        print("  [1] Start all 5 microservices in background (up -d) [default]")
        print("  [2] Stop all microservices (down)")
        print("  [3] View microservices logs (logs -f)")
        print("  [4] Inspect microservices status (ps)")
        print("  [5] Target specific microservice (ingress, inference, telemetry, storage, gateway)")
        try:
            act_choice = input(_colourise("Enter action [1-5] (default: 1): ", "1;33")).strip() or "1"
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            return 0
        args.command = "compose"
        args.microservices = True
        args.type = "microservices"
        args.remote_host = remote_host
        args.remote_user = remote_user
        args.remote_port = remote_port
        args.remote_auth = remote_auth
        args.remote_key = remote_key
        args.remote_dir = remote_dir
        if act_choice == "5":
            try:
                target = input(_colourise("Enter microservice name [ingress/inference/telemetry/storage/gateway]: ", "1;33")).strip()
            except (KeyboardInterrupt, EOFError):
                print("\nOperation cancelled.")
                return 0
            args.compose_action = "up"
            args.services = [target] if target else []
        else:
            act_map = {"1": "up", "2": "down", "3": "logs", "4": "ps"}
            args.compose_action = act_map.get(act_choice, "up")
        return run_compose(args)

    elif choice == "5":
        # systemd Service Management
        print("\nSelect systemd action:")
        print("  [1] Inspect service status [default]")
        print("  [2] Install and enable service at boot")
        print("  [3] View journal logs (journalctl -u edge-vision-monitor -f)")
        print("  [4] Restart service")
        print("  [5] Stop service")
        try:
            sys_choice = input(_colourise("Enter action [1-5] (default: 1): ", "1;33")).strip() or "1"
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            return 0
        sys_map = {"1": "status", "2": "install", "3": "logs", "4": "restart", "5": "stop"}
        args.command = "systemd"
        args.systemd_action = sys_map.get(sys_choice, "status")
        if args.systemd_action == "install":
            args.start_now = True
        return run_systemd(args)

    elif choice == "6":
        # Pre-flight Hardware Diagnostics Check
        log_step("Executing Hardware Diagnostic Tool")
        try:
            from scripts.diagnose import main as run_diagnostics
            return run_diagnostics() or 0
        except Exception as exc:
            log_error(f"Failed to run diagnostics: {exc}")
            return 1

    elif choice == "7":
        # Service Comparison Matrix
        print_service_matrix()
        return 0

    elif choice == "0":
        print("Exiting.")
        return 0

    else:
        log_error(f"Invalid option selected: '{choice}'")
        return 1


# ==============================================================================
# 5. CLI Argument Parser & Orchestrator
# ==============================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Edge Vision Monitor: Unified Application Entry Point & Deployment Manager.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive deployment selection menu (prompt)
  python main.py
  python main.py --prompt

  # Native on-device deployment
  python main.py run --port 8000 --reload
  python main.py run --service telemetry
  python main.py --mode native

  # Container Compose deployment
  python main.py compose up -d
  python main.py compose -m up -d
  python main.py compose up -m ingress
  python main.py compose matrix
  python main.py --mode microservices

  # systemd deployment
  python main.py systemd install --start-now
  python main.py systemd status
  python main.py systemd logs
  python main.py systemd restart
  python main.py --mode systemd

  # Hardware diagnostics check
  python main.py diagnose
        """,
    )

    # Top-level global flags
    parser.add_argument(
        "-i", "--prompt", "--interactive",
        action="store_true",
        help="Prompt interactive deployment selection menu",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Disable interactive deployment selection prompt and execute default",
    )
    parser.add_argument(
        "--mode",
        choices=["native", "compose", "podman", "microservices", "systemd", "run", "diagnose"],
        help="Explicit deployment mode selection (native | compose | microservices | systemd | diagnose)",
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to YAML configuration file (default: config/config.yaml)",
    )
    parser.add_argument(
        "--host",
        type=str,
        help="Server host/IP binding interface (default: 0.0.0.0)",
    )
    parser.add_argument(
        "-H", "--remote-host",
        type=str,
        default=None,
        help="Target remote host IP address or hostname for remote container compose execution (e.g. 192.168.1.100 or user@host)",
    )
    parser.add_argument(
        "-u", "--remote-user",
        type=str,
        default=None,
        help="Remote privileged login username (e.g. root, iotgwai)",
    )
    parser.add_argument(
        "--remote-port",
        type=int,
        default=22,
        help="Remote SSH port (default: 22)",
    )
    parser.add_argument(
        "-k", "--remote-key",
        type=str,
        default=None,
        help="Path to SSH identity private key file",
    )
    parser.add_argument(
        "--remote-dir",
        type=str,
        default="~/edge-vision-monitor",
        help="Working directory of project on remote host (default: ~/edge-vision-monitor)",
    )
    parser.add_argument(
        "--remote-method",
        choices=["ssh", "daemon"],
        default="ssh",
        help="Remote execution method: direct ssh execution (default) or container daemon connection (daemon)",
    )
    parser.add_argument(
        "--remote-auth",
        choices=["password", "key"],
        default="password",
        help="SSH authentication method: password (default, prevents auth failure) or key",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Server HTTP port (default: 8000)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development (native mode)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of server worker processes (native mode)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Application logging verbosity (default: INFO)",
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Run pre-flight hardware diagnostic check before launching",
    )

    subparsers = parser.add_subparsers(dest="command", help="Deployment and operational subcommands")

    # --- Subcommand: run / native ---
    run_parser = subparsers.add_parser("run", aliases=["native"], help="Start application natively on host/device")
    run_parser.add_argument(
        "--service",
        choices=["all", "gateway", "ingress", "inference", "telemetry", "storage"],
        default="all",
        help="Target microservice subsystem to execute (default: all)",
    )
    run_parser.add_argument("--host", type=str, help="Server host/IP binding interface (default: 0.0.0.0)")
    run_parser.add_argument("--port", type=int, help="Server HTTP port (default: 8000)")
    run_parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    run_parser.add_argument("--workers", type=int, default=1, help="Number of worker processes")
    run_parser.add_argument("--log-level", type=str, choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], help="Log verbosity")
    run_parser.add_argument("--config", type=str, help="Path to YAML config file")
    run_parser.add_argument("--diagnose", action="store_true", help="Execute hardware diagnostics before startup")

    # --- Subcommand: compose / podman ---
    compose_parser = subparsers.add_parser(
        "compose", aliases=["podman"], help="Manage Podman / Docker Compose containerised deployment"
    )
    compose_parser.add_argument(
        "compose_action",
        nargs="?",
        default="up",
        choices=["up", "down", "restart", "build", "logs", "ps", "status", "matrix", "services"],
        help="Compose operation to perform (default: up, or view matrix / services)",
    )
    compose_parser.add_argument(
        "-m", "--microservices",
        action="store_true",
        help="Deploy decomposed microservices architecture using compose.microservices.yaml",
    )
    compose_parser.add_argument(
        "--type",
        choices=["monolith", "microservices"],
        default=None,
        help="Container architecture deployment option (monolith | microservices)",
    )
    compose_parser.add_argument(
        "-H", "--remote-host",
        type=str,
        default=None,
        help="Target remote host IP address or hostname for remote container compose execution (e.g. 192.168.1.100 or user@host)",
    )
    compose_parser.add_argument(
        "-u", "--remote-user",
        type=str,
        default=None,
        help="Remote privileged login username (e.g. root, iotgwai)",
    )
    compose_parser.add_argument(
        "--remote-port",
        type=int,
        default=22,
        help="Remote SSH port (default: 22)",
    )
    compose_parser.add_argument(
        "-k", "--remote-key",
        type=str,
        default=None,
        help="Path to SSH identity private key file",
    )
    compose_parser.add_argument(
        "--remote-dir",
        type=str,
        default="~/edge-vision-monitor",
        help="Working directory of project on remote host (default: ~/edge-vision-monitor)",
    )
    compose_parser.add_argument(
        "--remote-method",
        choices=["ssh", "daemon"],
        default="ssh",
        help="Remote execution method: direct ssh execution (default) or container daemon connection (daemon)",
    )
    compose_parser.add_argument(
        "--remote-auth",
        choices=["password", "key"],
        default="password",
        help="SSH authentication method: password (default, prevents auth failure) or key",
    )
    compose_parser.add_argument(
        "services",
        nargs="*",
        help="Optional specific service names to target (e.g. ingress, inference, telemetry, storage, gateway)",
    )
    compose_parser.add_argument("-f", "--file", type=str, help="Path to compose.yaml file")
    compose_parser.add_argument("-d", "--detach", action="store_true", default=True, help="Run containers in background")
    compose_parser.add_argument("--no-detach", action="store_true", help="Run containers in foreground")
    compose_parser.add_argument("--build", action="store_true", help="Build images before starting containers")
    compose_parser.add_argument("--no-cache", action="store_true", help="Do not use cache when building images")
    compose_parser.add_argument("-v", "--volumes", action="store_true", help="Remove named volumes on down")
    compose_parser.add_argument("--follow", action="store_true", default=True, help="Follow log output")
    compose_parser.add_argument("--tail", type=int, default=100, help="Number of lines to show for logs")
    compose_parser.add_argument("--engine", choices=["podman", "docker"], help="Explicitly force compose engine")

    # --- Subcommand: systemd ---
    systemd_parser = subparsers.add_parser("systemd", help="Manage systemd service integration on Linux host")
    systemd_parser.add_argument(
        "systemd_action",
        nargs="?",
        default="status",
        choices=["install", "uninstall", "start", "stop", "restart", "status", "logs", "show", "generate"],
        help="systemd action to perform (default: status)",
    )
    systemd_parser.add_argument("--user", type=str, help="Service execution user (default: current user)")
    systemd_parser.add_argument("--group", type=str, default="video", help="Service execution group (default: video)")
    systemd_parser.add_argument("--python", type=str, help="Custom Python interpreter binary path")
    systemd_parser.add_argument("--host", type=str, default="0.0.0.0", help="Binding host in systemd service")
    systemd_parser.add_argument("--port", type=int, default=8000, help="Binding port in systemd service")
    systemd_parser.add_argument("--start-now", action="store_true", help="Start service immediately after install")
    systemd_parser.add_argument("--no-enable", action="store_true", help="Do not enable service at boot")
    systemd_parser.add_argument("-n", "--lines", type=int, default=50, help="Number of journal log lines to display")

    # --- Subcommand: diagnose ---
    subparsers.add_parser("diagnose", help="Run hardware, PCIe, V4L2, and driver diagnostic inspection")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    print_banner()

    # Resolve mode / command
    command = args.command
    mode = getattr(args, "mode", None)

    if mode:
        if mode in ("native", "run"):
            command = "run"
        elif mode in ("compose", "podman"):
            command = "compose"
        elif mode == "microservices":
            command = "compose"
            args.microservices = True
        elif mode == "systemd":
            command = "systemd"
        elif mode == "diagnose":
            command = "diagnose"

    # Interactive deployment menu prompt if explicitly requested or running without subcommands in an interactive TTY
    prompt_requested = getattr(args, "prompt", False)
    no_prompt = getattr(args, "no_prompt", False)
    if not command and (prompt_requested or (sys.stdin.isatty() and not no_prompt)):
        return prompt_deployment_menu(args)

    # Default action: run native on-device
    if not command:
        command = "run"

    if command in ("run", "native"):
        return run_native(args)
    elif command in ("compose", "podman"):
        return run_compose(args)
    elif command == "systemd":
        return run_systemd(args)
    elif command == "diagnose":
        log_step("Executing Hardware Diagnostic Tool")
        try:
            from scripts.diagnose import main as run_diagnostics
            return run_diagnostics() or 0
        except Exception as exc:
            log_error(f"Failed to run diagnostics: {exc}")
            return 1
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
