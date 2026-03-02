#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  server3-tv-browser-youtube-pause.sh <brave|firefox>

Examples:
  server3-tv-browser-youtube-pause.sh brave
  server3-tv-browser-youtube-pause.sh firefox
USAGE
}

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 2
fi

BROWSER_LC="${1,,}"
case "${BROWSER_LC}" in
  brave|brave-browser)
    WINDOW_FILTER="brave-browser"
    ;;
  firefox)
    WINDOW_FILTER="firefox"
    ;;
  *)
    echo "Unsupported browser: $1" >&2
    usage >&2
    exit 2
    ;;
esac

if ! command -v wmctrl >/dev/null 2>&1 || ! command -v xdotool >/dev/null 2>&1; then
  echo "wmctrl and xdotool are required." >&2
  exit 3
fi

if ! systemctl is-active --quiet lightdm.service; then
  echo "lightdm desktop is not active." >&2
  exit 4
fi

if ! id tv >/dev/null 2>&1; then
  echo "tv user not found." >&2
  exit 4
fi

TV_UID="$(id -u tv)"
ENV_VARS=("DISPLAY=:0" "XAUTHORITY=/home/tv/.Xauthority")
BUS_PATH="/run/user/${TV_UID}/bus"
if [[ -S "${BUS_PATH}" ]]; then
  ENV_VARS+=("DBUS_SESSION_BUS_ADDRESS=unix:path=${BUS_PATH}")
fi

WINDOW_ID="$({
  sudo -u tv env "${ENV_VARS[@]}" wmctrl -lx 2>/dev/null \
    | awk -v filter="${WINDOW_FILTER}" 'tolower($0) ~ filter {print $1}' \
    | tail -n 1
} || true)"

if [[ -z "${WINDOW_ID}" ]]; then
  echo "No ${BROWSER_LC} window found." >&2
  exit 5
fi

sudo -u tv env "${ENV_VARS[@]}" wmctrl -i -a "${WINDOW_ID}" >/dev/null 2>&1 || true
sleep 0.2

# Click player region to ensure keystrokes target the page/video.
sudo -u tv env "${ENV_VARS[@]}" xdotool mousemove --window "${WINDOW_ID}" 640 360 click 1 >/dev/null 2>&1 || true
sleep 0.2

# Use explicit media pause to avoid accidental toggle.
sudo -u tv env "${ENV_VARS[@]}" xdotool key --window "${WINDOW_ID}" --clearmodifiers XF86AudioPause >/dev/null 2>&1 || true

echo "[server3-tv-browser-youtube-pause] browser=${BROWSER_LC} window_id=${WINDOW_ID}"
