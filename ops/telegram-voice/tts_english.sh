#!/usr/bin/env bash
# English TTS using Microsoft Edge TTS (free, no API key).
# Usage: echo "text to speak" | tts_english.sh [--speed 1.5]
# Env: TTS_VOICE, TTS_SPEED, TTS_OUT_DIR
# Output: path to OGG Opus file (suitable for Telegram sendVoice)
set -euo pipefail

VOICE="${TTS_VOICE:-en-US-AriaNeural}"
SPEED="${TTS_SPEED:-1.35}"
OUT_DIR="${TTS_OUT_DIR:-/tmp/tts}"
TEXT="${1:-}"

mkdir -p "$OUT_DIR"

if [[ -z "${TEXT}" ]]; then
  TEXT="$(cat)"
fi

TEXT="$(echo "$TEXT" | tr '\n' ' ' | sed 's/  */ /g')"
if [[ -z "${TEXT// }" ]]; then
  echo "No text provided" >&2
  exit 1
fi

TS="$(date +%s)"
MP3_FILE="${OUT_DIR}/tts-${TS}.mp3"
OGG_FILE="${OUT_DIR}/tts-${TS}.ogg"

# Generate speech with edge-tts
edge-tts --voice "$VOICE" --text "$TEXT" --write-media "$MP3_FILE" >/dev/null 2>&1

# Convert to OGG Opus (Telegram voice note format: mono 16kHz)
# Apply speed adjustment via atempo filter if not 1.0x
if [[ "$SPEED" != "1.0" ]]; then
  ffmpeg -y -i "$MP3_FILE" -filter:a "atempo=${SPEED}" -c:a libopus -b:a 16k -ar 16000 -ac 1 "$OGG_FILE" >/dev/null 2>&1
else
  ffmpeg -y -i "$MP3_FILE" -c:a libopus -b:a 16k -ar 16000 -ac 1 "$OGG_FILE" >/dev/null 2>&1
fi

rm -f "$MP3_FILE"

echo "$OGG_FILE"
