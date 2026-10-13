"""
Unit tests for the Edge Vision Monitor root CLI entry point (main.py).
Tests argument parsing, mode resolution, compose engine discovery, and systemd unit generation.
"""

from __future__ import annotations

import argparse
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


def test_run_systemd_show(capsys):
    parser = build_parser()
    args = parser.parse_args(["systemd", "show", "--user", "myuser"])
    with patch("shutil.which", return_value="/bin/systemctl"):
        ret = run_systemd(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "User=myuser" in captured.out
        assert "ExecStart=" in captured.out


def test_run_native_nonexistent_config():
    parser = build_parser()
    args = parser.parse_args(["run", "--config", "/nonexistent/config.yaml"])
    ret = run_native(args)
    assert ret == 1
