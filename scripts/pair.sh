#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HERMES="${HERMES_HOME:-$HOME/.hermes}"
PORT="${ZALO_BRIDGE_PORT:-3001}"
SESSION="${ZALO_SESSION_DIR:-$HERMES/zalo/session}"
export HERMES_HOME="$HERMES"
export ZALO_SESSION_DIR="$SESSION"
mkdir -p "$SESSION"
echo "Hermes_Zalo bridge :$PORT"
echo "QR: $SESSION/qr.png  or  http://127.0.0.1:$PORT/qr.png"
cd "$ROOT/bridge"
exec node bridge.js --port "$PORT" --session "$SESSION"
