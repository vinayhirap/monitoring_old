#!/usr/bin/env bash
# ===============================================================
#  MarketLens — backend launcher (FastAPI + SQLite/Postgres) — Linux/macOS
#
#  Reads MARKETLENS_MODE=prod from env to disable hot-reload + bind
#  to multiple workers (production). Default is dev (single worker,
#  hot-reload on, uvicorn auto-restart on file change).
# ===============================================================
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/backend"

# Pick python3 first (most distros), fall back to python
if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "ERROR: Python not found. Install Python 3.11+ first." >&2
    echo "  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip" >&2
    echo "  RHEL/Amazon Linux: sudo yum install python3.11 python3.11-pip" >&2
    exit 1
fi

if [ ! -d .venv ]; then
    echo "[setup] Creating Python virtualenv..."
    "$PY" -m venv .venv || {
        echo "Failed to create venv." >&2
        echo "  On Debian/Ubuntu: sudo apt install python3-venv" >&2
        echo "  On RHEL/Amazon Linux: ensure python3-pip is installed" >&2
        exit 1
    }
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# Only reinstall deps when requirements.txt is NEWER than the marker file,
# or when the marker doesn't exist (fresh venv / first run).
REQ_MARKER=".venv/.requirements.installed"
if [ ! -f "$REQ_MARKER" ] || [ requirements.txt -nt "$REQ_MARKER" ]; then
    echo "[setup] Installing/upgrading Python dependencies (this may take a few minutes on first run)..."
    python -m pip install --upgrade pip >/dev/null
    pip install -r requirements.txt || {
        echo "pip install failed. See output above." >&2
        exit 1
    }
    touch "$REQ_MARKER"
else
    echo "[setup] Dependencies up-to-date (skipping pip install)."
fi

if [ ! -f ../.env ]; then
    if [ -f ../.env.example ]; then
        echo "[setup] No .env found — copying .env.example. Edit it with real values before going to prod."
        cp ../.env.example ../.env
    else
        echo "[setup] No .env or .env.example found — using process env only."
    fi
fi

MODE="${MARKETLENS_MODE:-dev}"
PORT="${BACKEND_PORT:-8000}"
HOST="${BACKEND_HOST:-0.0.0.0}"

echo ""
echo "==============================================================="
echo " MarketLens backend ($MODE mode) → http://$HOST:$PORT"
echo " Interactive API docs:           http://$HOST:$PORT/docs"
echo "==============================================================="
echo ""

if [ "$MODE" = "prod" ]; then
    # Production: no hot-reload, multiple workers (CPU count, capped at 4)
    WORKERS="${BACKEND_WORKERS:-$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)}"
    if [ "$WORKERS" -gt 4 ]; then WORKERS=4; fi
    exec python -m uvicorn app.main:app \
        --host "$HOST" --port "$PORT" \
        --workers "$WORKERS" --log-level info --no-access-log
else
    # Dev: hot-reload via run.py (single worker)
    exec python run.py
fi
