#!/usr/bin/env bash
# ===============================================================
#  MarketLens — frontend launcher (Next.js) — Linux/macOS
#
#  MARKETLENS_MODE=prod → `npm run build && npm start` (production)
#  Default            → `npm run dev` (hot-reload, source maps)
# ===============================================================
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/frontend"

if ! command -v node >/dev/null 2>&1; then
    echo "ERROR: Node.js not found. Install Node 18+ first." >&2
    echo "  Ubuntu/Debian: see https://github.com/nodesource/distributions" >&2
    echo "  Or via nvm:    https://github.com/nvm-sh/nvm" >&2
    exit 1
fi

NODE_MAJOR="$(node -v | sed 's/v\([0-9]*\).*/\1/')"
if [ "$NODE_MAJOR" -lt 18 ]; then
    echo "ERROR: Node 18+ required (detected v$NODE_MAJOR). Next.js 14 needs >=18.17." >&2
    exit 1
fi

if [ ! -d node_modules ]; then
    echo "[setup] Installing npm packages (first run, ~2 min)..."
    npm install || { echo "npm install failed." >&2; exit 1; }
fi

MODE="${MARKETLENS_MODE:-dev}"
PORT="${FRONTEND_PORT:-3000}"

echo ""
echo "==============================================================="
echo " MarketLens UI ($MODE mode) → http://localhost:$PORT"
echo "==============================================================="
echo ""

if [ "$MODE" = "prod" ]; then
    # Build once per run — Next.js skips work if .next/ is up-to-date
    echo "[build] Compiling production bundle..."
    npm run build
    exec npx next start -p "$PORT"
else
    exec npx next dev -p "$PORT"
fi
