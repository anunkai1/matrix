#!/usr/bin/env bash
set -euo pipefail

TARGET_ENV="/etc/default/telegram-architect-bridge"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TRANSCRIBE_CMD="${REPO_ROOT}/ops/telegram-voice/transcribe_voice.sh {file}"

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo -n "$@"
  fi
}

if ! run_privileged test -f "${TARGET_ENV}"; then
  echo "missing ${TARGET_ENV}; create it first from infra/env/telegram-architect-bridge.env.example" >&2
  exit 1
fi

tmp_file="$(mktemp)"
trap 'rm -f "${tmp_file}"' EXIT

run_privileged cat "${TARGET_ENV}" > "${tmp_file}"

python3 - "${tmp_file}" "${TRANSCRIBE_CMD}" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

path = Path(sys.argv[1])
transcribe_cmd = sys.argv[2]

updates = {
    "TELEGRAM_VOICE_TRANSCRIBE_CMD": transcribe_cmd,
    "TELEGRAM_VOICE_TRANSCRIBE_TIMEOUT_SECONDS": "180",
    "TELEGRAM_VOICE_WHISPER_VENV": "/home/architect/.local/share/telegram-voice/venv",
    "TELEGRAM_VOICE_WHISPER_MODEL": "base",
    "TELEGRAM_VOICE_WHISPER_DEVICE": "cpu",
    "TELEGRAM_VOICE_WHISPER_COMPUTE_TYPE": "int8",
}

lines = path.read_text(encoding="utf-8").splitlines()
seen: set[str] = set()
out: list[str] = []

for line in lines:
    if not line or line.lstrip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    key = line.split("=", 1)[0].strip()
    if key in updates:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)

for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")

path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY

run_privileged install -m 0644 "${tmp_file}" "${TARGET_ENV}"

echo "Updated ${TARGET_ENV} voice transcription settings"
