#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <media_url>" >&2
  exit 2
fi

MEDIA_URL="$1"
if [[ ! "${MEDIA_URL}" =~ ^https?:// ]]; then
  echo "media url must start with http:// or https://" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
YTDLP_BIN="${TELEGRAM_MEDIA_YTDLP_BIN:-yt-dlp}"
VOICE_TRANSCRIBE_SCRIPT="${TELEGRAM_MEDIA_TRANSCRIBE_VOICE_SCRIPT:-${SCRIPT_DIR}/transcribe_voice.sh}"
TMP_BASE_DIR="${TELEGRAM_MEDIA_TMP_DIR:-/tmp}"

if ! command -v "${YTDLP_BIN}" >/dev/null 2>&1; then
  echo "yt-dlp is not installed" >&2
  exit 2
fi

if [[ ! -x "${VOICE_TRANSCRIBE_SCRIPT}" ]]; then
  echo "voice transcribe script not found: ${VOICE_TRANSCRIBE_SCRIPT}" >&2
  exit 2
fi

TMP_DIR="$(mktemp -d "${TMP_BASE_DIR%/}/media-transcribe-XXXXXX")"
cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

COOKIE_ARGS=()
if [[ -n "${TELEGRAM_MEDIA_COOKIES_FILE:-}" ]]; then
  COOKIE_ARGS+=(--cookies "${TELEGRAM_MEDIA_COOKIES_FILE}")
elif [[ -n "${TELEGRAM_MEDIA_COOKIES_FROM_BROWSER:-}" ]]; then
  COOKIE_ARGS+=(--cookies-from-browser "${TELEGRAM_MEDIA_COOKIES_FROM_BROWSER}")
fi

YTDLP_COMMON_ARGS=(
  --no-warnings
  --no-progress
  --restrict-filenames
  -o "${TMP_DIR}/%(id)s.%(ext)s"
)

extract_from_json3() {
  local json_file="$1"
  python3 - "$json_file" <<'PY'
import json
import re
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as handle:
    payload = json.load(handle)

events = payload.get("events", []) if isinstance(payload, dict) else []
chunks = []
for event in events:
    if not isinstance(event, dict):
        continue
    segs = event.get("segs")
    if not isinstance(segs, list):
        continue
    text = "".join(
        seg.get("utf8", "")
        for seg in segs
        if isinstance(seg, dict) and isinstance(seg.get("utf8"), str)
    )
    text = re.sub(r"\s+", " ", text).strip()
    if text:
        chunks.append(text)

# Remove immediate duplicates common in auto-captions.
result = []
for chunk in chunks:
    if result and chunk == result[-1]:
        continue
    result.append(chunk)

print(" ".join(result).strip())
PY
}

# 1) Captions-first path (fast and cheap).
if "${YTDLP_BIN}" "${YTDLP_COMMON_ARGS[@]}" "${COOKIE_ARGS[@]}" \
  --skip-download \
  --write-auto-sub \
  --write-sub \
  --sub-langs "ru-orig,ru,en-orig,en" \
  --sub-format "json3" \
  "${MEDIA_URL}" >/dev/null 2>&1; then
  while IFS= read -r -d '' candidate; do
    if [[ ! -s "${candidate}" ]]; then
      continue
    fi
    transcript="$(extract_from_json3 "${candidate}" 2>/dev/null || true)"
    if [[ -n "${transcript}" ]]; then
      printf '%s\n' "${transcript}"
      exit 0
    fi
  done < <(find "${TMP_DIR}" -maxdepth 1 -type f -name '*.json3' -print0)
fi

# 2) Download audio and run local Whisper transcribe pipeline.
"${YTDLP_BIN}" "${YTDLP_COMMON_ARGS[@]}" "${COOKIE_ARGS[@]}" \
  -f "bestaudio/best" \
  "${MEDIA_URL}" >/dev/null

audio_file=""
while IFS= read -r -d '' candidate; do
  case "${candidate}" in
    *.json3|*.vtt|*.srt|*.ass|*.part|*.tmp)
      continue
      ;;
  esac
  audio_file="${candidate}"
  break
done < <(find "${TMP_DIR}" -maxdepth 1 -type f -print0)

if [[ -z "${audio_file}" ]]; then
  echo "failed to download media audio" >&2
  exit 1
fi

"${VOICE_TRANSCRIBE_SCRIPT}" "${audio_file}"
