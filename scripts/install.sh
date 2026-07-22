#!/usr/bin/env bash
# Install Hermes_Zalo into ~/.hermes (or $HERMES_HOME)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HERMES="${HERMES_HOME:-$HOME/.hermes}"
BRIDGE_SRC="$ROOT/bridge"
PLUGIN_SRC="$ROOT/plugin"
BRIDGE_DST="$HERMES/scripts/zalo-bridge"
PLUGIN_DST="$HERMES/plugins/zalo-platform"

echo "== Hermes_Zalo install =="
echo "Repo:   $ROOT"
echo "Hermes: $HERMES"

[[ -d "$HERMES" ]] || { echo "Hermes home missing: $HERMES"; exit 1; }
[[ -f "$BRIDGE_SRC/bridge.js" ]] || { echo "bridge.js missing"; exit 1; }
command -v node >/dev/null || { echo "node required"; exit 1; }

( cd "$BRIDGE_SRC" && npm install )

link_dir() {
  local dst="$1" src="$2"
  mkdir -p "$(dirname "$dst")"
  if [[ -L "$dst" ]]; then
    echo "symlink ok: $dst"
    return
  fi
  if [[ -e "$dst" ]]; then
    echo "exists (not symlink): $dst — remove manually"; exit 1
  fi
  ln -s "$src" "$dst"
  echo "linked $dst -> $src"
}

link_dir "$BRIDGE_DST" "$BRIDGE_SRC"
link_dir "$PLUGIN_DST" "$PLUGIN_SRC"

ENVF="$HERMES/.env"
touch "$ENVF"
append_if_missing() {
  local key="$1" val="$2"
  if ! grep -qE "^${key}=" "$ENVF" 2>/dev/null; then
    echo "${key}=${val}" >>"$ENVF"
    echo "env + $key"
  fi
}
append_if_missing ZALO_ENABLED true
append_if_missing ZALO_BRIDGE_PORT 3001
append_if_missing ZALO_ALLOWED_USERS '*'
append_if_missing ZALO_ALLOW_ALL_USERS true
append_if_missing ZALO_FORWARD_SELF_MESSAGES true
append_if_missing ZALO_SEND_SEEN true
append_if_missing ZALO_POLL_INTERVAL 0.4

if command -v hermes >/dev/null; then
  hermes plugins enable zalo-platform || true
else
  echo "hermes CLI not on PATH — run: hermes plugins enable zalo-platform"
fi

mkdir -p "$HERMES/zalo/session"
echo "OK. Pair: bash $ROOT/scripts/pair.sh"
