#!/usr/bin/env bash
set -euo pipefail

VENV_PATH="${TELEGRAM_VOICE_WHISPER_VENV:-/home/architect/.local/share/telegram-voice/venv}"

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo -n "$@"
  fi
}

run_privileged apt-get update
run_privileged apt-get install -y ffmpeg python3-venv

mkdir -p "$(dirname "${VENV_PATH}")"
if [[ ! -x "${VENV_PATH}/bin/python3" ]]; then
  python3 -m venv "${VENV_PATH}"
fi

"${VENV_PATH}/bin/pip" install --upgrade pip wheel
"${VENV_PATH}/bin/pip" install --upgrade faster-whisper

"${VENV_PATH}/bin/python3" - <<'PY'
from faster_whisper import WhisperModel
print("faster-whisper import: ok")
PY

echo "Voice transcription runtime ready at ${VENV_PATH}"
