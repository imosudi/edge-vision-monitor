#!/usr/bin/env python3
"""
Edge Vision Monitor - Main Application Entry Point & Deployment Manager.

Unified orchestration interface for:
  1. On-Device Native Deployment: Direct Python/FastAPI/Uvicorn execution.
  2. Podman Compose Deployment: Rootless, least-privilege containerization.
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


# ==============================================================================
# Helper / Terminal Formatting Utilities
# ==============================================================================

def _colorize(text: str, color_code: str) -> str:
    if sys.stdout.isatty():
        return f"\033[{color_code}m{text}\033[0m"
    return text


def log_info(msg: str):
    print(f"{_colorize('[INFO]', '32;1')} {msg}")


def log_warn(msg: str):
    print(f"{_colorize('[WARN]', '33;1')} {msg}")


def log_error(msg: str):
    print(f"{_colorize('[ERROR]', '31;1')} {msg}", file=sys.stderr)


def log_step(title: str):
    print(f"\n{_colorize('===>', '36;1')} {_colorize(title, '1')}")


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
    print(_colorize(banner, "36"))


# ==============================================================================
# 1. On-Device Native Deployment
# ==============================================================================

def run_native(args: argparse.Namespace) -> int:
    """Start Edge Vision Monitor natively using Uvicorn."""
    log_step("Starting On-Device Native Deployment")

    # Set custom config file path if specified
    if getattr(args, "config", None):
        cfg_path = Path(args.config).resolve()
        if not cfg_path.exists():
            log_error(f"Config file not found: {cfg_path}")
            return 1
        os.environ["EVM_CONFIG_PATH"] = str(cfg_path)
        log_info(f"Using configuration file: {cfg_path}")

    # Run optional hardware diagnostics first
    if getattr(args, "diagnose", False):
        log_step("Running Pre-flight Hardware Diagnostics")
        try:
            from scripts.diagnose import main as run_diagnostics
            run_diagnostics()
        except ImportError:
            log_warn("Diagnostic script 'scripts.diagnose' could not be imported. Skipping diagnostics.")

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
    """Manage Podman/Docker Compose deployment."""
    log_step("Managing Container Compose Deployment")

    compose_file = getattr(args, "file", None) or (PROJECT_ROOT / "compose.yaml")
    compose_file = Path(compose_file).resolve()

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
    log_info(f"Detected container engine: {_colorize(engine_name, '32')}")
    log_info(f"Using compose file:        {compose_file}")

    # Check hardware nodes
    if not Path("/dev/hailo0").exists():
        log_warn("Hardware node /dev/hailo0 not detected on host. Container inference will operate in Mock/CPU mode.")
    if not Path("/dev/video0").exists():
        log_warn("Video device /dev/video0 not detected on host. Video file playback will be required.")

    # Determine action (default: 'up')
    action = getattr(args, "compose_action", None) or "up"

    cmd = list(compose_cmd)
    cmd.extend(["-f", str(compose_file)])

    if action == "up":
        cmd.append("up")
        if not getattr(args, "no_detach", False):
            cmd.append("-d")
        if getattr(args, "build", False):
            cmd.append("--build")
    elif action == "down":
        cmd.append("down")
        if getattr(args, "volumes", False):
            cmd.append("-v")
    elif action == "restart":
        cmd.append("restart")
    elif action == "build":
        cmd.append("build")
        if getattr(args, "no_cache", False):
            cmd.append("--no-cache")
    elif action == "logs":
        cmd.append("logs")
        if getattr(args, "follow", True):
            cmd.append("-f")
        if getattr(args, "tail", None):
            cmd.extend(["--tail", str(args.tail)])
    elif action in ("ps", "status"):
        cmd.append("ps")
    else:
        cmd.append(action)

    log_info(f"Executing: {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
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
        print(f"\n{_colorize('--- Generated systemd Service Configuration ---', '36')}")
        print(unit_content)
        print(_colorize("--------------------------------------------------", "36"))
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
# 4. CLI Argument Parser & Orchestrator
# ==============================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Edge Vision Monitor — Unified Application Entry Point & Deployment Manager.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Native on-device deployment (default)
  python main.py
  python main.py run --port 8000 --reload
  python main.py --mode native

  # Podman Compose deployment
  python main.py compose up -d
  python main.py podman up --build
  python main.py podman down
  python main.py podman logs -f
  python main.py --mode compose

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
        "--mode",
        choices=["native", "compose", "podman", "systemd", "run", "diagnose"],
        help="Explicit deployment mode selection (native | compose | systemd | diagnose)",
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
    run_parser.add_argument("--host", type=str, help="Server host/IP binding interface (default: 0.0.0.0)")
    run_parser.add_argument("--port", type=int, help="Server HTTP port (default: 8000)")
    run_parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    run_parser.add_argument("--workers", type=int, default=1, help="Number of worker processes")
    run_parser.add_argument("--log-level", type=str, choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], help="Log verbosity")
    run_parser.add_argument("--config", type=str, help="Path to YAML config file")
    run_parser.add_argument("--diagnose", action="store_true", help="Execute hardware diagnostics before startup")

    # --- Subcommand: compose / podman ---
    compose_parser = subparsers.add_parser(
        "compose", aliases=["podman"], help="Manage Podman / Docker Compose containerized deployment"
    )
    compose_parser.add_argument(
        "compose_action",
        nargs="?",
        default="up",
        choices=["up", "down", "restart", "build", "logs", "ps", "status"],
        help="Compose operation to perform (default: up)",
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
        elif mode == "systemd":
            command = "systemd"
        elif mode == "diagnose":
            command = "diagnose"

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
