#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

python3 -m py_compile \
  "${REPO_ROOT}/src/telegram_bridge/main.py" \
  "${REPO_ROOT}/src/telegram_bridge/executor.py" \
  "${REPO_ROOT}/src/telegram_bridge/handlers.py" \
  "${REPO_ROOT}/src/telegram_bridge/media.py" \
  "${REPO_ROOT}/src/telegram_bridge/session_manager.py" \
  "${REPO_ROOT}/src/telegram_bridge/state_store.py" \
  "${REPO_ROOT}/src/telegram_bridge/stream_buffer.py" \
  "${REPO_ROOT}/src/telegram_bridge/transport.py"
python3 "${REPO_ROOT}/src/telegram_bridge/main.py" --self-test

echo "smoke-test: ok"
