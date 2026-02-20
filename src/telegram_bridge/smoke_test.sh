#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

python3 -m py_compile "${REPO_ROOT}/src/telegram_bridge/main.py"
python3 "${REPO_ROOT}/src/telegram_bridge/main.py" --self-test

echo "smoke-test: ok"
