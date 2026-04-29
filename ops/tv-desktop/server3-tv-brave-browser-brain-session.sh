#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  server3-tv-brave-browser-brain-session.sh [url]

Examples:
  server3-tv-brave-browser-brain-session.sh
  server3-tv-brave-browser-brain-session.sh https://x.com/home
USAGE
}

if [[ $# -gt 1 ]]; then
  usage >&2
  exit 2
fi

URL="${1:-about:blank}"
TV_HOME="/home/tv"
REMOTE_DEBUG_PORT="${SERVER3_TV_BRAVE_REMOTE_DEBUGGING_PORT:-9223}"
BRAVE_PROFILE_DIR="${TV_HOME}/.local/state/server3-browser-brain-brave-profile"
BROWSER_BIN="$(command -v brave-browser || true)"

if [[ -z "${BROWSER_BIN}" ]]; then
  echo "Brave browser binary not found." >&2
  exit 3
fi

if ! systemctl is-active --quiet lightdm.service; then
  /usr/local/bin/server3-tv-start
  sleep 2
fi

if ! id tv >/dev/null 2>&1; then
  echo "tv user not found." >&2
  exit 4
fi

TV_UID="$(id -u tv)"
DISPLAY_VALUE=":0"
XAUTHORITY_VALUE="${TV_HOME}/.Xauthority"
RUNTIME_DIR="/run/user/${TV_UID}"
BUS_PATH="/run/user/${TV_UID}/bus"

wait_for_tv_session() {
  local attempts=20
  local delay=1
  local attempt
  for attempt in $(seq 1 "${attempts}"); do
    if pgrep -u tv -x xfce4-session >/dev/null 2>&1 \
      && sudo -u tv test -f "${XAUTHORITY_VALUE}" \
      && sudo -u tv test -d "${RUNTIME_DIR}"; then
      return 0
    fi
    sleep "${delay}"
  done

  echo "TV desktop session did not become ready." >&2
  return 1
}

wait_for_cdp_endpoint() {
  local attempts=20
  local delay=1
  local attempt
  for attempt in $(seq 1 "${attempts}"); do
    if curl -fsS "http://127.0.0.1:${REMOTE_DEBUG_PORT}/json/version" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${delay}"
  done

  echo "Timed out waiting for Brave CDP endpoint on port ${REMOTE_DEBUG_PORT}." >&2
  return 1
}

build_env_vars() {
  ENV_VARS=(
    "HOME=${TV_HOME}"
    "USER=tv"
    "LOGNAME=tv"
    "DISPLAY=${DISPLAY_VALUE}"
    "XAUTHORITY=${XAUTHORITY_VALUE}"
    "XDG_RUNTIME_DIR=${RUNTIME_DIR}"
  )

  if [[ -S "${BUS_PATH}" ]]; then
    ENV_VARS+=("DBUS_SESSION_BUS_ADDRESS=unix:path=${BUS_PATH}")
  fi
}

wait_for_tv_session
build_env_vars

sudo install -d -m 755 -o tv -g tv "${TV_HOME}/.local/state" "${BRAVE_PROFILE_DIR}"
sudo -u tv env "${ENV_VARS[@]}" nohup "${BROWSER_BIN}" \
  --no-default-browser-check \
  --no-first-run \
  --start-maximized \
  --no-sandbox \
  --disable-setuid-sandbox \
  --disable-gpu \
  --disable-gpu-compositing \
  --disable-software-rasterizer \
  --in-process-gpu \
  --no-zygote \
  --single-process \
  --use-angle=swiftshader \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port="${REMOTE_DEBUG_PORT}" \
  --user-data-dir="${BRAVE_PROFILE_DIR}" \
  --new-window "${URL}" >/tmp/server3-tv-brave-browser-brain.log 2>&1 < /dev/null &

wait_for_cdp_endpoint

echo "[server3-tv-brave-browser-brain-session] browser=brave url=${URL} remote_debugging_port=${REMOTE_DEBUG_PORT} profile=${BRAVE_PROFILE_DIR}"
