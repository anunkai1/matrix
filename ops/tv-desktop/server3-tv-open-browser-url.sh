#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  server3-tv-open-browser-url.sh <firefox|brave> <url>

Examples:
  server3-tv-open-browser-url.sh firefox https://www.youtube.com
  server3-tv-open-browser-url.sh brave "https://www.youtube.com/results?search_query=deephouse+2026"
USAGE
}

if [[ $# -lt 2 ]]; then
  usage >&2
  exit 2
fi

BROWSER_RAW="$1"
URL="$2"

case "${BROWSER_RAW,,}" in
  firefox)
    BROWSER_BIN="$(command -v firefox || true)"
    ;;
  brave|brave-browser)
    BROWSER_BIN="$(command -v brave-browser || true)"
    ;;
  *)
    echo "Unsupported browser: ${BROWSER_RAW}" >&2
    usage >&2
    exit 2
    ;;
esac

if [[ -z "${BROWSER_BIN}" ]]; then
  echo "Browser binary not found for '${BROWSER_RAW}'." >&2
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
XAUTHORITY_VALUE="/home/tv/.Xauthority"
BUS_PATH="/run/user/${TV_UID}/bus"

ENV_VARS=("DISPLAY=${DISPLAY_VALUE}" "XAUTHORITY=${XAUTHORITY_VALUE}")
if [[ -S "${BUS_PATH}" ]]; then
  ENV_VARS+=("DBUS_SESSION_BUS_ADDRESS=unix:path=${BUS_PATH}")
fi

# Launch detached so bridge returns immediately.
if [[ "${BROWSER_RAW,,}" == "firefox" ]]; then
  sudo -u tv env "${ENV_VARS[@]}" nohup "${BROWSER_BIN}" --new-window "${URL}" >/tmp/server3-tv-browser.log 2>&1 < /dev/null &
else
  sudo -u tv env "${ENV_VARS[@]}" nohup "${BROWSER_BIN}" \
    --no-default-browser-check \
    --no-first-run \
    --start-maximized \
    --new-window "${URL}" >/tmp/server3-tv-browser.log 2>&1 < /dev/null &
fi

echo "[server3-tv-open-browser-url] launched browser=${BROWSER_RAW,,} url=${URL}"
