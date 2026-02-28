#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <voice_file_path>" >&2
  exit 2
fi

VOICE_FILE="$1"
if [[ ! -f "${VOICE_FILE}" ]]; then
  echo "voice file not found: ${VOICE_FILE}" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_PATH="${TELEGRAM_VOICE_WHISPER_VENV:-/home/architect/.local/share/telegram-voice/venv}"
PYTHON_BIN="${VENV_PATH}/bin/python3"
VOICE_SOCKET_PATH="${TELEGRAM_VOICE_WHISPER_SOCKET_PATH:-/tmp/telegram-voice-whisper.sock}"
VOICE_IDLE_TIMEOUT_SECONDS="${TELEGRAM_VOICE_WHISPER_IDLE_TIMEOUT_SECONDS:-3600}"
VOICE_CLIENT_TIMEOUT_SECONDS="${TELEGRAM_VOICE_TRANSCRIBE_TIMEOUT_SECONDS:-180}"
VOICE_SERVICE_LOG_PATH="${TELEGRAM_VOICE_WHISPER_LOG_PATH:-/tmp/telegram-voice-whisper.log}"
SERVICE_SCRIPT="${REPO_ROOT}/src/telegram_bridge/voice_transcribe_service.py"

PREPROCESSED_VOICE_FILE="${VOICE_FILE}"
TMP_PREPROCESSED_FILE=""

cleanup() {
  if [[ -n "${TMP_PREPROCESSED_FILE}" && -f "${TMP_PREPROCESSED_FILE}" ]]; then
    rm -f "${TMP_PREPROCESSED_FILE}"
  fi
}
trap cleanup EXIT

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "voice runtime is not installed at ${VENV_PATH}. run: bash ${REPO_ROOT}/ops/telegram-voice/install_faster_whisper.sh" >&2
  exit 2
fi

if [[ ! -f "${SERVICE_SCRIPT}" ]]; then
  echo "voice transcribe service script not found: ${SERVICE_SCRIPT}" >&2
  exit 2
fi

prepare_voice_file() {
  if ! command -v ffmpeg >/dev/null 2>&1; then
    return
  fi
  TMP_PREPROCESSED_FILE="$(mktemp --suffix=.wav /tmp/telegram-voice-preprocessed-XXXXXX)"
  if ffmpeg -nostdin -hide_banner -loglevel error -y \
    -i "${VOICE_FILE}" \
    -ac 1 \
    -ar 16000 \
    -af "highpass=f=80,lowpass=f=8000" \
    "${TMP_PREPROCESSED_FILE}"; then
    PREPROCESSED_VOICE_FILE="${TMP_PREPROCESSED_FILE}"
    return
  fi
  rm -f "${TMP_PREPROCESSED_FILE}"
  TMP_PREPROCESSED_FILE=""
}

ping_service() {
  "${PYTHON_BIN}" "${SERVICE_SCRIPT}" ping \
    --socket "${VOICE_SOCKET_PATH}" \
    --timeout 2 >/dev/null 2>&1
}

start_service() {
  nohup "${PYTHON_BIN}" "${SERVICE_SCRIPT}" server \
    --socket "${VOICE_SOCKET_PATH}" \
    --idle-timeout "${VOICE_IDLE_TIMEOUT_SECONDS}" >>"${VOICE_SERVICE_LOG_PATH}" 2>&1 &
}

ensure_service() {
  if ping_service; then
    return 0
  fi
  start_service
  for _ in $(seq 1 50); do
    if ping_service; then
      return 0
    fi
    sleep 0.1
  done
  return 1
}

prepare_voice_file

if ! ensure_service; then
  echo "voice transcribe service failed to start (see ${VOICE_SERVICE_LOG_PATH})" >&2
  exit 1
fi

"${PYTHON_BIN}" "${SERVICE_SCRIPT}" client \
  --socket "${VOICE_SOCKET_PATH}" \
  --audio-path "${PREPROCESSED_VOICE_FILE}" \
  --timeout "${VOICE_CLIENT_TIMEOUT_SECONDS}"
