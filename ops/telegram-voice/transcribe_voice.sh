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

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "voice runtime is not installed at ${VENV_PATH}. run: bash ${REPO_ROOT}/ops/telegram-voice/install_faster_whisper.sh" >&2
  exit 2
fi

exec "${PYTHON_BIN}" "${REPO_ROOT}/src/telegram_bridge/voice_transcribe.py" "${VOICE_FILE}"
