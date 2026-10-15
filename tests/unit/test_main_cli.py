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

