#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${SIGNALTUBE_BROWSER_STATE_DIR:-$ROOT/private/signaltube/browser-brain}"
PID_FILE="$STATE_DIR/signaltube-browser-brain.pid"
LOG_FILE="$STATE_DIR/signaltube-browser-brain.log"
PYTHON_BIN="${SIGNALTUBE_BROWSER_PYTHON:-/var/lib/server3-browser-brain/venv/bin/python}"
PORT="${SIGNALTUBE_BROWSER_PORT:-47832}"
HOST="${SIGNALTUBE_BROWSER_HOST:-127.0.0.1}"
BROWSER_BIN="${SIGNALTUBE_BROWSER_BIN:-/usr/bin/brave-browser}"

usage() {
  printf 'Usage: %s {start|stop|status}\n' "$0" >&2
}

is_running() {
  [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

start() {
  mkdir -p "$STATE_DIR"
  if is_running; then
    printf 'SignalTube lab browser already running on %s:%s pid=%s\n' "$HOST" "$PORT" "$(cat "$PID_FILE")"
    return 0
  fi
  if [[ ! -x "$PYTHON_BIN" ]]; then
    printf 'Python runtime not executable: %s\n' "$PYTHON_BIN" >&2
    return 1
  fi
  if [[ ! -x "$BROWSER_BIN" ]]; then
    printf 'Browser executable not found: %s\n' "$BROWSER_BIN" >&2
    return 1
  fi
  (
    cd "$ROOT"
    export PYTHONUNBUFFERED=1
    export BROWSER_BRAIN_HOST="$HOST"
    export BROWSER_BRAIN_PORT="$PORT"
    export BROWSER_BRAIN_CONNECTION_MODE=managed
    export BROWSER_BRAIN_BROWSER_EXECUTABLE="$BROWSER_BIN"
    export BROWSER_BRAIN_STATE_DIR="$STATE_DIR"
    export BROWSER_BRAIN_PROFILE_DIR="$STATE_DIR/profile"
    export BROWSER_BRAIN_CAPTURE_DIR="$STATE_DIR/captures"
    export BROWSER_BRAIN_HEADLESS=true
    export BROWSER_BRAIN_LOG_ACTIONS=true
    export BROWSER_BRAIN_ALLOWED_ORIGINS="https://www.youtube.com,https://youtube.com,https://consent.youtube.com,https://accounts.google.com"
    export BROWSER_BRAIN_BLOCKED_ORIGINS=""
    export BROWSER_BRAIN_ALLOW_FILE_URLS=false
    nohup "$PYTHON_BIN" -m src.browser_brain.main >>"$LOG_FILE" 2>&1 &
    printf '%s\n' "$!" >"$PID_FILE"
  )
  sleep 1
  if ! is_running; then
    printf 'SignalTube lab browser failed to start; see %s\n' "$LOG_FILE" >&2
    return 1
  fi
  printf 'SignalTube lab browser running on %s:%s pid=%s\n' "$HOST" "$PORT" "$(cat "$PID_FILE")"
}

stop() {
  if ! is_running; then
    rm -f "$PID_FILE"
    printf 'SignalTube lab browser is not running\n'
    return 0
  fi
  pid="$(cat "$PID_FILE")"
  kill "$pid"
  for _ in $(seq 1 20); do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$PID_FILE"
      printf 'SignalTube lab browser stopped\n'
      return 0
    fi
    sleep 0.2
  done
  printf 'SignalTube lab browser did not stop cleanly; pid=%s\n' "$pid" >&2
  return 1
}

status() {
  if is_running; then
    printf 'SignalTube lab browser running on %s:%s pid=%s\n' "$HOST" "$PORT" "$(cat "$PID_FILE")"
  else
    printf 'SignalTube lab browser is not running\n'
    return 1
  fi
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) usage; exit 2 ;;
esac
