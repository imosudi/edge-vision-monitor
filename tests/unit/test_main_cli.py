"""
Unit tests for the Edge Vision Monitor root CLI entry point (main.py).
Tests argument parsing, mode resolution, compose engine discovery, and systemd unit generation.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import main
from main import (
    build_parser,
    find_compose_command,
    generate_systemd_unit,
    run_native,
    run_systemd,
)


def test_build_parser_defaults():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.command is None
    assert args.mode is None
    assert args.port is None
    assert args.host is None
    assert args.reload is False


def test_parser_subcommands():
    parser = build_parser()

    # Test run subcommand
    args_run = parser.parse_args(["run", "--host", "127.0.0.1", "--port", "9000", "--reload"])
    assert args_run.command == "run"
    assert args_run.host == "127.0.0.1"
    assert args_run.port == 9000
    assert args_run.reload is True

    # Test native alias
    args_native = parser.parse_args(["native", "--port", "8080"])
    assert args_native.command == "native"
    assert args_native.port == 8080

    # Test compose subcommand
    args_compose = parser.parse_args(["compose", "down", "-v"])
    assert args_compose.command == "compose"
    assert args_compose.compose_action == "down"
    assert args_compose.volumes is True

    # Test podman alias
    args_podman = parser.parse_args(["podman", "up", "--build"])
    assert args_podman.command == "podman"
    assert args_podman.compose_action == "up"
    assert args_podman.build is True

    # Test systemd subcommand
    args_sysd = parser.parse_args(["systemd", "status"])
    assert args_sysd.command == "systemd"
    assert args_sysd.systemd_action == "status"

    # Test diagnose subcommand
    args_diag = parser.parse_args(["diagnose"])
    assert args_diag.command == "diagnose"

    # Test benchmark subcommand
    args_bench = parser.parse_args([
        "benchmark",
        "--workload", "B",
        "--duration", "120",
        "--target-temp", "98.5",
        "--safety-limit", "101.0",
        "--streams", "6",
        "--simulate",
        "--format", "json",
        "-o", "reports/traj.json",
    ])
    assert args_bench.command == "benchmark"
    assert args_bench.workload == "B"
    assert args_bench.duration == 120.0
    assert args_bench.target_temp == 98.5
    assert args_bench.safety_limit == 101.0
    assert args_bench.streams == 6
    assert args_bench.simulate is True
    assert args_bench.format == "json"
    assert args_bench.output == "reports/traj.json"

    # Test stress alias
    args_stress = parser.parse_args(["stress", "-w", "C"])
    assert args_stress.command == "stress"
    assert args_stress.workload == "C"


def test_parser_mode_flags():

    parser = build_parser()
    args = parser.parse_args(["--mode", "compose"])
    assert args.mode == "compose"

    args = parser.parse_args(["--mode", "systemd"])
    assert args.mode == "systemd"

    args = parser.parse_args(["--mode", "native", "--port", "8080"])
    assert args.mode == "native"
    assert args.port == 8080


def test_generate_systemd_unit():
    workdir = Path("/opt/edge-vision-monitor")
    python_bin = Path("/opt/edge-vision-monitor/.venv/bin/python")
    config_path = Path("/opt/edge-vision-monitor/config/config.yaml")

    unit = generate_systemd_unit(
        user="testuser",
        group="video",
        workdir=workdir,
        python_bin=python_bin,
        config_path=config_path,
        host="0.0.0.0",
        port=8000,
    )

    assert "User=testuser" in unit
    assert "Group=video" in unit
    assert "WorkingDirectory=/opt/edge-vision-monitor" in unit
    assert "ExecStart=/opt/edge-vision-monitor/.venv/bin/python /opt/edge-vision-monitor/main.py run --host 0.0.0.0 --port 8000" in unit
    assert "Restart=always" in unit
    assert "ProtectSystem=full" in unit
    assert "ReadWritePaths=/opt/edge-vision-monitor" in unit


def test_find_compose_command():
    with patch("shutil.which") as mock_which, patch("subprocess.run") as mock_run:
        # Scenario 1: podman available and podman compose works
        mock_which.side_effect = lambda x: "/usr/bin/" + x if x == "podman" else None
        mock_run.return_value = MagicMock(returncode=0)

        cmd = find_compose_command()
        assert cmd == ["podman", "compose"]

    with patch("shutil.which") as mock_which, patch("subprocess.run") as mock_run:
        # Scenario 2: only podman-compose available
        mock_which.side_effect = lambda x: "/usr/bin/" + x if x == "podman-compose" else None
        mock_run.return_value = MagicMock(returncode=0)

        cmd = find_compose_command()
        assert cmd == ["podman-compose"]

    with patch("shutil.which") as mock_which, patch("subprocess.run") as mock_run:
        # Scenario 3: only docker compose available
        mock_which.side_effect = lambda x: "/usr/bin/" + x if x == "docker" else None
        mock_run.return_value = MagicMock(returncode=0)

        cmd = find_compose_command()
        assert cmd == ["docker", "compose"]


def test_get_python_executable(tmp_path):
    from main import get_python_executable

    # When .venv/bin/python exists
    fake_venv = tmp_path / ".venv" / "bin"
    fake_venv.mkdir(parents=True)
    fake_py = fake_venv / "python"
    fake_py.touch()

    with patch("sys.prefix", "/base"), patch("sys.base_prefix", "/base"):
        py_bin = get_python_executable(tmp_path)
        assert py_bin == fake_py.absolute()


def test_run_systemd_show(capsys):
    parser = build_parser()
    args = parser.parse_args(["systemd", "show", "--user", "myuser", "--python", "/opt/custom/python"])
    with patch("shutil.which", return_value="/bin/systemctl"):
        ret = run_systemd(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "User=myuser" in captured.out
        assert "/opt/custom/python" in captured.out
        assert "ExecStart=" in captured.out


def test_run_native_nonexistent_config():
    parser = build_parser()
    args = parser.parse_args(["run", "--config", "/nonexistent/config.yaml"])
    ret = run_native(args)
    assert ret == 1


def test_parser_microservices_flags():
    parser = build_parser()

    # Test -m / --microservices flag
    args_m = parser.parse_args(["compose", "-m", "up"])
    assert args_m.microservices is True
    assert args_m.compose_action == "up"

    args_ms = parser.parse_args(["compose", "--microservices", "down"])
    assert args_ms.microservices is True
    assert args_ms.compose_action == "down"

    # Test --type flag
    args_type_ms = parser.parse_args(["compose", "--type", "microservices", "ps"])
    assert args_type_ms.type == "microservices"

    args_type_mono = parser.parse_args(["compose", "--type", "monolith", "ps"])
    assert args_type_mono.type == "monolith"


def test_parser_compose_services_and_matrix_actions():
    parser = build_parser()

    args_mat = parser.parse_args(["compose", "matrix"])
    assert args_mat.compose_action == "matrix"

    args_srv = parser.parse_args(["compose", "services"])
    assert args_srv.compose_action == "services"


def test_parser_run_service_flag():
    parser = build_parser()

    args_tel = parser.parse_args(["run", "--service", "telemetry"])
    assert args_tel.service == "telemetry"

    args_ing = parser.parse_args(["run", "--service", "ingress"])
    assert args_ing.service == "ingress"

    args_inf = parser.parse_args(["run", "--service", "inference"])
    assert args_inf.service == "inference"

    args_sto = parser.parse_args(["run", "--service", "storage"])
    assert args_sto.service == "storage"

    args_gw = parser.parse_args(["run", "--service", "gateway"])
    assert args_gw.service == "gateway"

    args_all = parser.parse_args(["run", "--service", "all"])
    assert args_all.service == "all"


def test_print_service_matrix(capsys):
    from main import print_service_matrix

    print_service_matrix()
    captured = capsys.readouterr()
    assert "EDGE VISION MONITOR: LEAST-PRIVILEGE SERVICE COMPARISON MATRIX" in captured.out
    assert "edge-vision-ingress" in captured.out
    assert "edge-vision-inference" in captured.out
    assert "edge-vision-telemetry" in captured.out
    assert "edge-vision-storage" in captured.out
    assert "edge-vision-gateway" in captured.out
    assert "compose.microservices.yaml" in captured.out


def test_run_compose_microservices_invokes_correct_file_and_service_mapping():
    from main import run_compose

    parser = build_parser()
    args = parser.parse_args(["compose", "-m", "up", "ingress"])

    with patch("main.find_compose_command", return_value=["docker", "compose"]), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        ret = run_compose(args)
        assert ret == 0
        mock_run.assert_called_once()
        called_cmd = mock_run.call_args[0][0]

        # Verify compose.microservices.yaml is specified
        assert any("compose.microservices.yaml" in part for part in called_cmd)
        # Verify alias 'ingress' was mapped to 'edge-vision-ingress'
        assert "edge-vision-ingress" in called_cmd


def test_run_native_standalone_service_worker():
    parser = build_parser()
    args = parser.parse_args(["run", "--service", "telemetry"])

    try:
        with patch("app.core.lifecycle.run_service_worker", return_value=0) as mock_worker:
            ret = run_native(args)
            assert ret == 0
            mock_worker.assert_called_once_with("telemetry")
    finally:
        os.environ.pop("EVM_SERVICE", None)


def test_parser_prompt_flags():
    parser = build_parser()

    args_p = parser.parse_args(["--prompt"])
    assert args_p.prompt is True

    args_i = parser.parse_args(["-i"])
    assert args_i.prompt is True

    args_np = parser.parse_args(["--no-prompt"])
    assert args_np.no_prompt is True


def test_prompt_deployment_menu_exit():
    from main import prompt_deployment_menu

    parser = build_parser()
    args = parser.parse_args([])

    with patch("builtins.input", return_value="0"):
        ret = prompt_deployment_menu(args)
        assert ret == 0


def test_prompt_deployment_menu_matrix():
    from main import prompt_deployment_menu

    parser = build_parser()
    args = parser.parse_args([])

    with patch("builtins.input", return_value="7"), \
         patch("main.print_service_matrix") as mock_matrix:
        ret = prompt_deployment_menu(args)
        assert ret == 0
        mock_matrix.assert_called_once()


def test_prompt_deployment_menu_native():
    from main import prompt_deployment_menu

    parser = build_parser()
    args = parser.parse_args([])

    with patch("builtins.input", return_value="1"), \
         patch("main.run_native", return_value=0) as mock_native:
        ret = prompt_deployment_menu(args)
        assert ret == 0
        mock_native.assert_called_once()


def test_prompt_deployment_menu_microservices_local():
    from main import prompt_deployment_menu

    parser = build_parser()
    args = parser.parse_args([])

    with patch("builtins.input", side_effect=["4", "1", "1"]), \
         patch("main.run_compose", return_value=0) as mock_compose:
        ret = prompt_deployment_menu(args)
        assert ret == 0
        mock_compose.assert_called_once()
        assert args.microservices is True
        assert args.remote_host is None
        assert args.compose_action == "up"


def test_prompt_deployment_menu_microservices_remote():
    from main import prompt_deployment_menu

    parser = build_parser()
    args = parser.parse_args([])

    # Inputs: choice 4, target 2, host, privileged user, port, auth (1=password), dir, action 1
    with patch("builtins.input", side_effect=["4", "2", "192.168.1.100", "iotgwai", "2222", "1", "~/edge-vision-monitor", "1"]), \
         patch("main.run_compose", return_value=0) as mock_compose:
        ret = prompt_deployment_menu(args)
        assert ret == 0
        mock_compose.assert_called_once()
        assert args.microservices is True
        assert args.remote_host == "192.168.1.100"
        assert args.remote_user == "iotgwai"
        assert args.remote_port == 2222
        assert args.remote_auth == "password"
        assert args.remote_dir == "~/edge-vision-monitor"
        assert args.compose_action == "up"


def test_prompt_deployment_menu_microservices_remote_defaults():
    from main import prompt_deployment_menu

    parser = build_parser()
    args = parser.parse_args([])

    # Inputs: choice 4, target 2, Enter for default host, Enter for default user, Enter for default port, Enter for password auth, Enter for dir, Enter for action 1
    with patch("builtins.input", side_effect=["4", "2", "", "", "", "1", "", "1"]), \
         patch("main.run_compose", return_value=0) as mock_compose:
        ret = prompt_deployment_menu(args)
        assert ret == 0
        mock_compose.assert_called_once()
        assert args.microservices is True
        assert args.remote_host == "10.236.235.118"
        assert args.remote_user == "iotgwai"
        assert args.remote_port == 22
        assert args.remote_auth == "password"
        assert args.remote_dir == "~/edge-vision-monitor"
        assert args.compose_action == "up"


def test_prompt_deployment_menu_microservices_remote_interrupt_cancels():
    from main import prompt_deployment_menu

    parser = build_parser()
    args = parser.parse_args([])

    with patch("builtins.input", side_effect=["4", "2", KeyboardInterrupt]), \
         patch("main.run_compose") as mock_compose:
        ret = prompt_deployment_menu(args)
        assert ret == 0
        mock_compose.assert_not_called()


def test_run_compose_with_remote_ssh_execution():
    from main import run_compose

    parser = build_parser()
    args = parser.parse_args(["compose", "-m", "-H", "192.168.1.100", "-u", "iotgwai", "--remote-port", "22", "up"])

    with patch("main.find_compose_command", return_value=["docker", "compose"]), \
         patch("shutil.which", return_value="/usr/bin/ssh"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        ret = run_compose(args)
        assert ret == 0
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]

        assert cmd[0] == "ssh"
        assert "-o" in cmd
        assert "StrictHostKeyChecking=accept-new" in cmd
        assert "PubkeyAuthentication=no" in cmd
        assert "iotgwai@192.168.1.100" in cmd
        assert any("compose.microservices.yaml" in part for part in cmd)
        assert any("up -d" in part for part in cmd)


def test_run_compose_with_remote_daemon_connection():
    from main import run_compose

    parser = build_parser()
    args = parser.parse_args(["compose", "-m", "-H", "192.168.1.100", "--remote-method", "daemon", "up"])

    with patch("main.find_compose_command", return_value=["docker", "compose"]), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        ret = run_compose(args)
        assert ret == 0
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        env = mock_run.call_args[1]["env"]

        assert cmd[0] == "docker"
        assert cmd[1:3] == ["-H", "ssh://192.168.1.100"]
        assert "compose" in cmd
        assert env.get("DOCKER_HOST") == "ssh://192.168.1.100"


def test_parser_remote_host_flags():
    parser = build_parser()

    args_h = parser.parse_args(["compose", "-H", "10.0.0.5", "-u", "root", "--remote-port", "2222", "-k", "/path/to/key", "--remote-dir", "/app"])
    assert args_h.remote_host == "10.0.0.5"
    assert args_h.remote_user == "root"
    assert args_h.remote_port == 2222
    assert args_h.remote_key == "/path/to/key"
    assert args_h.remote_dir == "/app"

    args_rh = parser.parse_args(["compose", "--remote-host", "user@pi.local"])
    assert args_rh.remote_host == "user@pi.local"

    args_top = parser.parse_args(["-H", "10.0.0.9", "-u", "pi"])
    assert args_top.remote_host == "10.0.0.9"
    assert args_top.remote_user == "pi"

