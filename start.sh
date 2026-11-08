#!/usr/bin/env bash
# ===============================================================
#  MarketLens — one-shot launcher for Linux/macOS
#  Starts backend in background, frontend in foreground.
#  Ctrl-C cleanly terminates both.
#
#  Usage:
#    ./start.sh          # development (hot-reload, npm run dev)
#    ./start.sh --prod   # production (no reload, npm run build && start)
# ===============================================================
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

# --prod flag → tell child scripts to launch production builds
MODE="dev"
for arg in "$@"; do
    if [ "$arg" = "--prod" ] || [ "$arg" = "-p" ]; then
        MODE="prod"
    fi
done
export MARKETLENS_MODE="$MODE"

# Cleanup on exit — preserve original exit code so set -e errors surface
BACKEND_PID=""
cleanup() {
    local rc=$?
    echo ""
    echo "[stop] Shutting down MarketLens..."
    if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        kill -TERM "$BACKEND_PID" 2>/dev/null || true
        # Give uvicorn 3s to flush logs + close connections before SIGKILL
        for _ in 1 2 3; do
            kill -0 "$BACKEND_PID" 2>/dev/null || break
            sleep 1
        done
        kill -KILL "$BACKEND_PID" 2>/dev/null || true
    fi
    echo "[stop] Done. Logs preserved in: $LOG_DIR"
    exit "$rc"
}
trap cleanup INT TERM EXIT

echo "==============================================================="
echo "  MarketLens — starting backend + frontend ($MODE mode)"
echo "  Backend log:  $BACKEND_LOG"
echo "  Frontend log: $FRONTEND_LOG"
echo "==============================================================="

echo "[1/2] Launching backend in background..."
bash "$SCRIPT_DIR/start-backend.sh" > "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!
echo "      Backend PID: $BACKEND_PID"

echo "[1/2] Waiting up to 60s for backend to become healthy..."
HEALTHY=0
for i in $(seq 1 60); do
    if curl -s --max-time 1 http://localhost:8000/health >/dev/null 2>&1; then
        echo "      Backend is up (after ${i}s)."
        HEALTHY=1
        break
    fi
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo "ERROR: Backend died during startup. Last 40 lines of $BACKEND_LOG:" >&2
        tail -40 "$BACKEND_LOG" >&2
        exit 1
    fi
    sleep 1
done
if [ "$HEALTHY" != "1" ]; then
    echo "ERROR: Backend did not become healthy in 60s. See $BACKEND_LOG." >&2
    tail -40 "$BACKEND_LOG" >&2
    exit 1
fi

# Probe the detailed health endpoint to show which AI / optional layers
# are active. None of this is required for the app to function; it's
# diagnostic only — operators want to know what's loaded.
echo ""
echo "      AI / optional layer status:"
HEALTH_JSON=$(curl -s --max-time 3 'http://localhost:8000/api/health?detailed=true' || echo '{}')
# Prefer python3, fall back to the venv python so the parse works even if
# the host lacks a system python3 (deployed on minimal containers etc.)
PY_PARSE="$(command -v python3 || command -v python || echo "$SCRIPT_DIR/backend/.venv/bin/python")"
if [ -x "$PY_PARSE" ]; then
    echo "$HEALTH_JSON" | "$PY_PARSE" -c "
import json, sys
try:
    d = json.load(sys.stdin).get('subsystems', {})
except Exception:
    sys.exit(0)
def line(label, ok, detail=''):
    mark = '✓' if ok else '·'
    print(f'        {mark}  {label:<22} {detail}')
line('Picks scanner',         d.get('picks_scanner', {}).get('running', False),
       'every 5 min')
line('Online learner',        True,
       f\"n={d.get('calibrator', {}).get('n_samples', 0)} samples seen\")
line('Calibrator',            d.get('calibrator', {}).get('active', False),
       'active' if d.get('calibrator', {}).get('active') else 'awaiting >=300 evaluated signals')
line('Local LLM (optional)',  d.get('local_llm', {}).get('available', False),
       d.get('local_llm', {}).get('load_error') or 'set LOCAL_LLM_MODEL_PATH to enable')
line('Telegram bot',          d.get('telegram_bot', {}).get('configured', False),
       'set TELEGRAM_BOT_TOKEN to enable')
line('Twitter bot',           d.get('twitter_bot', {}).get('configured', False),
       'set TWITTER_* env vars to enable')
line('Login limiter backend', d.get('login_limiter', {}).get('ok', False),
       d.get('login_limiter', {}).get('backend', '?'))
line('Broker (operator)',     d.get('broker', {}).get('ok', False),
       d.get('broker', {}).get('mode', '?'))
line('Razorpay payments',     d.get('razorpay', {}).get('configured', False),
       'set RAZORPAY_* env vars to enable')
" 2>/dev/null || echo "      (could not parse health JSON; see $BACKEND_LOG)"
else
    echo "      (no python found to parse health JSON; see $BACKEND_LOG)"
fi
echo ""

echo "[2/2] Launching frontend (foreground — Ctrl-C to stop everything)..."
bash "$SCRIPT_DIR/start-frontend.sh" 2>&1 | tee "$FRONTEND_LOG"
