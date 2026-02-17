#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

python3 -m py_compile "${REPO_ROOT}/src/telegram_bridge/main.py"
python3 -m py_compile "${REPO_ROOT}/src/telegram_bridge/ha_control.py"
python3 "${REPO_ROOT}/src/telegram_bridge/main.py" --self-test
bash "${REPO_ROOT}/ops/home-assistant/validate_architect_package.sh"

echo "smoke-test: ok"
