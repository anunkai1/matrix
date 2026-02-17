#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PACKAGE_PATH="${REPO_ROOT}/infra/home_assistant/packages/architect_executor.yaml"

if [[ ! -s "${PACKAGE_PATH}" ]]; then
  echo "missing package file: ${PACKAGE_PATH}" >&2
  exit 1
fi

python3 - <<'PY'
from pathlib import Path

path = Path("infra/home_assistant/packages/architect_executor.yaml")
text = path.read_text(encoding="utf-8")
required = [
    "input_boolean:",
    "architect_schedule_climate_followup",
    "architect_clear_climate_followup",
    "architect_execute_climate_followup",
]
missing = [item for item in required if item not in text]
if missing:
    raise SystemExit(f"package validation failed, missing keys: {missing}")
print("architect package validation: ok")
PY
