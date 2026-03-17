#!/usr/bin/env bash
# Setup script for the OPC Tool
# Installs Python dependencies and builds the OPC Tool frontend.
#
# Usage:
#   ./scripts/setup_opc_tool.sh          # full setup
#   ./scripts/setup_opc_tool.sh --skip-frontend  # Python only

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

SKIP_FRONTEND=false
for arg in "$@"; do
    case "$arg" in
        --skip-frontend) SKIP_FRONTEND=true ;;
    esac
done

echo "=== OPC Tool Setup ==="
echo "Root directory: $ROOT_DIR"
echo ""

# ---- Python dependencies ----
echo "[1/3] Installing Python dependencies..."
if [ -d "$ROOT_DIR/.venv" ]; then
    PYTHON="$ROOT_DIR/.venv/bin/python"
    PIP="$ROOT_DIR/.venv/bin/pip"
    echo "  Using virtualenv: $ROOT_DIR/.venv"
else
    PYTHON="python3"
    PIP="pip3"
    echo "  No .venv found, using system Python"
fi

$PIP install -e "$ROOT_DIR" --quiet
echo "  Done."

# ---- OPC Tool frontend ----
if [ "$SKIP_FRONTEND" = true ]; then
    echo "[2/3] Skipping frontend build (--skip-frontend)"
else
    echo "[2/3] Building OPC Tool frontend..."
    OPC_FRONTEND="$ROOT_DIR/opc_frontend"
    if [ ! -d "$OPC_FRONTEND" ]; then
        echo "  ERROR: opc_frontend/ directory not found"
        exit 1
    fi

    if ! command -v npm &> /dev/null; then
        echo "  WARNING: npm not found. Skipping frontend build."
        echo "  Install Node.js to build the OPC Tool frontend."
    else
        cd "$OPC_FRONTEND"
        echo "  Installing npm packages..."
        npm install --silent 2>/dev/null
        echo "  Building production bundle..."
        npm run build --silent
        echo "  Done. Output: opc_frontend/dist/"
    fi
fi

# ---- Data directory ----
echo "[3/3] Creating data directory..."
DATA_DIR="${OPC_TOOL_DATA_DIR:-$ROOT_DIR/opc_tool_data}"
mkdir -p "$DATA_DIR"
echo "  Data directory: $DATA_DIR"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Start the OPC Tool:"
echo "  opc-tool"
echo "  # or: python -m opc_tool"
echo ""
echo "Web GUI: http://localhost:8001"
