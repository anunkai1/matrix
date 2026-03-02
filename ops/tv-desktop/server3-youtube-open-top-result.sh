#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  server3-youtube-open-top-result.sh --query "<text>" [--browser firefox|brave] [--min-duration-seconds <n>] [--no-autoplay]

Examples:
  server3-youtube-open-top-result.sh --query "deephouse 2026"
  server3-youtube-open-top-result.sh --query "mersheimer" --min-duration-seconds 600
USAGE
}

QUERY=""
BROWSER="firefox"
MIN_DURATION_SECONDS=0
AUTOPLAY=1
PLAYBACK_FALLBACK_ATTEMPTED=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --query)
      if [[ $# -lt 2 ]]; then
        usage >&2
        exit 2
      fi
      QUERY="$2"
      shift 2
      ;;
    --browser)
      if [[ $# -lt 2 ]]; then
        usage >&2
        exit 2
      fi
      BROWSER="$2"
      shift 2
      ;;
    --min-duration-seconds)
      if [[ $# -lt 2 ]]; then
        usage >&2
        exit 2
      fi
      MIN_DURATION_SECONDS="$2"
      shift 2
      ;;
    --no-autoplay)
      AUTOPLAY=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

maybe_force_playback_fallback() {
  local browser_lc="$1"
  if (( AUTOPLAY == 0 )); then
    return 0
  fi
  if [[ "${browser_lc}" != "firefox" ]]; then
    return 0
  fi
  if ! command -v wmctrl >/dev/null 2>&1 || ! command -v xdotool >/dev/null 2>&1; then
    echo "[server3-youtube-open-top-result] playback fallback skipped (wmctrl/xdotool missing)." >&2
    return 0
  fi

  local display_env="DISPLAY=:0"
  local xauth_env="XAUTHORITY=/home/tv/.Xauthority"
  local window_id=""
  local attempt
  for attempt in 1 2 3 4 5 6 7 8; do
    window_id="$(
      sudo -u tv env "${display_env}" "${xauth_env}" wmctrl -lx 2>/dev/null \
        | awk 'tolower($0) ~ /firefox/ {print $1}' \
        | tail -n 1
    )"
    if [[ -n "${window_id}" ]]; then
      break
    fi
    sleep 1
  done
  if [[ -z "${window_id}" ]]; then
    echo "[server3-youtube-open-top-result] playback fallback skipped (no firefox window id)." >&2
    return 0
  fi

  sleep 1
  sudo -u tv env "${display_env}" "${xauth_env}" wmctrl -i -a "${window_id}" >/dev/null 2>&1 || true
  sleep 1
  sudo -u tv env "${display_env}" "${xauth_env}" xdotool mousemove --window "${window_id}" 640 360 click 1 >/dev/null 2>&1 || true
  sleep 0.4
  sudo -u tv env "${display_env}" "${xauth_env}" xdotool key --window "${window_id}" --clearmodifiers k >/dev/null 2>&1 || true
  PLAYBACK_FALLBACK_ATTEMPTED=1
}

if [[ -z "${QUERY}" ]]; then
  echo "Missing --query" >&2
  usage >&2
  exit 2
fi

if ! [[ "${MIN_DURATION_SECONDS}" =~ ^[0-9]+$ ]]; then
  echo "--min-duration-seconds must be a non-negative integer." >&2
  exit 2
fi

if ! command -v yt-dlp >/dev/null 2>&1; then
  echo "yt-dlp is required. Install with: sudo apt-get install -y yt-dlp" >&2
  exit 3
fi

SEARCH_LINE="$(yt-dlp --flat-playlist --print '%(id)s|%(title)s|%(duration)s' "ytsearch1:${QUERY}" 2>/dev/null | head -n 1 || true)"
if [[ -z "${SEARCH_LINE}" ]]; then
  echo "Failed to resolve YouTube search result for query: ${QUERY}" >&2
  exit 4
fi

IFS='|' read -r VIDEO_ID TITLE DURATION_RAW <<<"${SEARCH_LINE}"

if [[ -z "${VIDEO_ID}" || "${VIDEO_ID}" == "NA" ]]; then
  echo "No playable top YouTube result found for query: ${QUERY}" >&2
  exit 4
fi

if [[ -z "${TITLE}" || "${TITLE}" == "NA" ]]; then
  TITLE="(unknown title)"
fi

DURATION_SECONDS="$(python3 - "${DURATION_RAW}" <<'PY'
import sys
raw = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
try:
    value = float(raw)
except Exception:
    print(0)
    raise SystemExit
if value < 0:
    value = 0
print(int(value))
PY
)"

if ! [[ "${DURATION_SECONDS}" =~ ^[0-9]+$ ]]; then
  DURATION_SECONDS=0
fi

URL="https://www.youtube.com/watch?v=${VIDEO_ID}"

if (( DURATION_SECONDS < MIN_DURATION_SECONDS )); then
  echo "Top result rejected: duration ${DURATION_SECONDS}s is below minimum ${MIN_DURATION_SECONDS}s" >&2
  echo "title=${TITLE}" >&2
  echo "url=${URL}" >&2
  exit 5
fi

FINAL_URL="${URL}"
if (( AUTOPLAY == 1 )); then
  if [[ "${FINAL_URL}" == *\?* ]]; then
    FINAL_URL+="&autoplay=1"
  else
    FINAL_URL+="?autoplay=1"
  fi
fi

"$(dirname "$0")/server3-tv-open-browser-url.sh" "${BROWSER}" "${FINAL_URL}"
maybe_force_playback_fallback "${BROWSER,,}"

echo "[server3-youtube-open-top-result] query=${QUERY} title=${TITLE} duration_seconds=${DURATION_SECONDS} url=${FINAL_URL} playback_fallback_attempted=${PLAYBACK_FALLBACK_ATTEMPTED}"
