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

echo "[server3-youtube-open-top-result] query=${QUERY} title=${TITLE} duration_seconds=${DURATION_SECONDS} url=${FINAL_URL}"
