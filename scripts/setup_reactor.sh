#!/usr/bin/env bash
# Setup script for the Reactor Digital Twin
# Installs Python dependencies, IPOPT solver, and builds the reactor frontend.
#
# Usage:
#   ./scripts/setup_reactor.sh                      # full setup
#   ./scripts/setup_reactor.sh --skip-frontend       # Python + IPOPT only
#   ./scripts/setup_reactor.sh --skip-ipopt          # Python + frontend only
#   ./scripts/setup_reactor.sh --with-opc-tool       # also set up OPC Tool

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPT_DIR/setup_common.sh"

SKIP_FRONTEND=false
SKIP_IPOPT=false
WITH_OPC_TOOL=false
for arg in "$@"; do
    case "$arg" in
        --skip-frontend) SKIP_FRONTEND=true ;;
        --skip-ipopt) SKIP_IPOPT=true ;;
        --with-opc-tool) WITH_OPC_TOOL=true ;;
    esac
done

echo "=== Reactor Digital Twin Setup ==="
echo "Root directory: $ROOT_DIR"
echo ""

# ---- Python environment ----
echo "[1/5] Setting up Python environment..."
PYTHON_CMD="$(ensure_python_runtime)"
ensure_repo_venv "$ROOT_DIR" "$PYTHON_CMD"

PYTHON="$ROOT_DIR/.venv/bin/python"
PIP="$ROOT_DIR/.venv/bin/pip"
echo "  Using virtualenv: $ROOT_DIR/.venv"

# ---- Python dependencies ----
echo "[2/5] Installing Python dependencies..."
"$PIP" install --upgrade pip --quiet
"$PIP" install -e "$ROOT_DIR[dev]" --quiet
echo "  Done."

# ---- IPOPT solver ----
if [ "$SKIP_IPOPT" = true ]; then
    echo "[3/5] Skipping IPOPT installation (--skip-ipopt)"
else
    echo "[3/5] Installing IPOPT solver via IDAES..."
    if "$PYTHON" -c "import idaes" 2>/dev/null; then
        echo "  IDAES already installed, getting extensions..."
    else
        echo "  Installing idaes-pse..."
        "$PIP" install idaes-pse --quiet
    fi
    "$PYTHON" -c "
import subprocess, sys
try:
    result = subprocess.run(
        [sys.executable, '-m', 'idaes', 'get-extensions', '--verbose'],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode == 0:
        print('  IPOPT extensions installed successfully.')
    else:
        print('  WARNING: IDAES get-extensions returned non-zero.')
        print('  You may need to install IPOPT manually.')
        print(f'  stderr: {result.stderr[:200]}')
except Exception as e:
    print(f'  WARNING: Failed to get IDAES extensions: {e}')
    print('  You can install IPOPT manually: conda install -c conda-forge ipopt')
"
fi

# ---- Reactor frontend ----
if [ "$SKIP_FRONTEND" = true ]; then
    echo "[4/5] Skipping frontend build (--skip-frontend)"
else
    echo "[4/5] Building reactor frontend..."
    FRONTEND="$ROOT_DIR/frontend"
    if [ ! -d "$FRONTEND" ]; then
        echo "  WARNING: frontend/ directory not found. Skipping."
    elif ! command -v npm &> /dev/null; then
        echo "  WARNING: npm not found. Skipping frontend build."
        echo "  Install Node.js to build the reactor frontend."
    else
        cd "$FRONTEND"
        echo "  Installing npm packages..."
        npm install --silent 2>/dev/null
        echo "  Building production bundle..."
        npm run build --silent
        echo "  Done. Output: frontend/dist/"
    fi
fi

# ---- Config directories ----
echo "[5/5] Ensuring config directories exist..."
mkdir -p "$ROOT_DIR/configs" "$ROOT_DIR/recipes"
echo "  Done."

# ---- OPC Tool (optional) ----
if [ "$WITH_OPC_TOOL" = true ]; then
    echo ""
    echo "--- Setting up OPC Tool ---"
    bash "$SCRIPT_DIR/setup_opc_tool.sh"
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Activate the virtualenv:"
echo "  source .venv/bin/activate"
echo ""
echo "Start the reactor:"
echo "  reactor"
echo "  # or: python -m reactor"
echo ""
echo "Web dashboard: http://localhost:8000"
if [ "$WITH_OPC_TOOL" = true ]; then
    echo "OPC Tool GUI:  http://localhost:8001"
fi
