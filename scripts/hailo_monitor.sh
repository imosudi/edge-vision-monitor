#!/usr/bin/env bash
# ==============================================================================
# Edge Vision Monitor - Hailo-8L NPU Live Monitor Launcher
# Sets HAILO_MONITOR=1 and runs live NPU monitor (chip temperature, load, FPS)
# ==============================================================================

set -euo pipefail

# Ensure Hailo monitor instrumentation is active
export HAILO_MONITOR=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Execute Python monitor script with passed arguments
exec python3 "$SCRIPT_DIR/hailo_monitor.py" "$@"
