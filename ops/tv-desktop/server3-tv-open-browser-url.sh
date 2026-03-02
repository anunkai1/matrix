#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  server3-tv-open-browser-url.sh <firefox|brave> <url> [--new-window]

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
REUSE_EXISTING_WINDOW=1

if [[ $# -gt 2 ]]; then
  case "$3" in
    --new-window)
      REUSE_EXISTING_WINDOW=0
      ;;
    *)
      echo "Unknown option: $3" >&2
      usage >&2
      exit 2
      ;;
  esac
fi

BROWSER_LC="${BROWSER_RAW,,}"

case "${BROWSER_LC}" in
  firefox)
    BROWSER_BIN="$(command -v firefox || true)"
    WINDOW_FILTER="firefox"
    ;;
  brave|brave-browser)
    BROWSER_BIN="$(command -v brave-browser || true)"
    WINDOW_FILTER="brave-browser"
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

# Reuse existing browser window when available (default behavior).
if (( REUSE_EXISTING_WINDOW == 1 )) && command -v wmctrl >/dev/null 2>&1 && command -v xdotool >/dev/null 2>&1; then
  WINDOW_ID="$(
    sudo -u tv env "${ENV_VARS[@]}" wmctrl -lx 2>/dev/null \
      | awk -v filter="${WINDOW_FILTER}" 'tolower($0) ~ filter {print $1}' \
      | tail -n 1
  )"
  if [[ -n "${WINDOW_ID}" ]]; then
    sudo -u tv env "${ENV_VARS[@]}" wmctrl -i -a "${WINDOW_ID}" >/dev/null 2>&1 || true
    sleep 0.2
    sudo -u tv env "${ENV_VARS[@]}" xdotool key --window "${WINDOW_ID}" --clearmodifiers ctrl+l >/dev/null 2>&1 || true
    sleep 0.2
    sudo -u tv env "${ENV_VARS[@]}" xdotool type --window "${WINDOW_ID}" --delay 1 "${URL}" >/dev/null 2>&1 || true
    sleep 0.1
    sudo -u tv env "${ENV_VARS[@]}" xdotool key --window "${WINDOW_ID}" --clearmodifiers Return >/dev/null 2>&1 || true
    echo "[server3-tv-open-browser-url] reused_existing_window=1 browser=${BROWSER_LC} url=${URL}"
    exit 0
  fi
fi

# Launch detached so bridge returns immediately when no reusable window is found.
if [[ "${BROWSER_LC}" == "firefox" ]]; then
  sudo -u tv env "${ENV_VARS[@]}" nohup "${BROWSER_BIN}" --new-window "${URL}" >/tmp/server3-tv-browser.log 2>&1 < /dev/null &
else
  sudo -u tv env "${ENV_VARS[@]}" nohup "${BROWSER_BIN}" \
    --no-default-browser-check \
    --no-first-run \
    --start-maximized \
    --new-window "${URL}" >/tmp/server3-tv-browser.log 2>&1 < /dev/null &
fi

echo "[server3-tv-open-browser-url] reused_existing_window=0 browser=${BROWSER_LC} url=${URL}"
