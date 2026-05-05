#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

"${PYTHON_BIN}" -m py_compile \
  "${REPO_ROOT}/src/architect_cli/main.py" \
  "${REPO_ROOT}/src/telegram_bridge/main.py" \
  "${REPO_ROOT}/src/telegram_bridge/executor.py" \
  "${REPO_ROOT}/src/telegram_bridge/handlers.py" \
  "${REPO_ROOT}/src/telegram_bridge/media.py" \
  "${REPO_ROOT}/src/telegram_bridge/session_manager.py" \
  "${REPO_ROOT}/src/telegram_bridge/state_store.py" \
  "${REPO_ROOT}/src/telegram_bridge/voice_transcribe_service.py" \
  "${REPO_ROOT}/src/telegram_bridge/stream_buffer.py" \
  "${REPO_ROOT}/src/telegram_bridge/transport.py"
"${PYTHON_BIN}" "${REPO_ROOT}/src/telegram_bridge/main.py" --self-test

echo "smoke-test: ok"
