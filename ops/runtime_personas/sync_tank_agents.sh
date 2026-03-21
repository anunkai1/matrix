#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

SOURCE_FILE="${REPO_ROOT}/infra/runtime_personas/tank.AGENTS.md"
TARGET_FILE="/home/tank/tankbot/AGENTS.md"
BACKUP_FILE="${TARGET_FILE}.pre-runtime-persona-sync"
MODE="check"

usage() {
  cat <<'EOF'
Usage:
  bash ops/runtime_personas/sync_tank_agents.sh [--check|--apply]

Modes:
  --check  Compare the tracked Tank persona with the live runtime file. (default)
  --apply  Copy the tracked Tank persona into the live runtime file, preserving a one-time backup.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)
      MODE="check"
      ;;
    --apply)
      MODE="apply"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ ! -f "${SOURCE_FILE}" ]]; then
  echo "[missing-source] ${SOURCE_FILE}" >&2
  exit 1
fi

if ! sudo test -f "${TARGET_FILE}"; then
  echo "[missing-target] ${TARGET_FILE}" >&2
  exit 1
fi

if sudo cmp -s "${SOURCE_FILE}" "${TARGET_FILE}"; then
  echo "[ok] Tank tracked persona matches the live runtime file"
  exit 0
fi

if [[ "${MODE}" == "check" ]]; then
  echo "[drift] Tank tracked persona differs from the live runtime file"
  sudo diff -u "${TARGET_FILE}" "${SOURCE_FILE}" || true
  exit 3
fi

if ! sudo test -f "${BACKUP_FILE}"; then
  sudo cp "${TARGET_FILE}" "${BACKUP_FILE}"
  sudo chown tank:tank "${BACKUP_FILE}"
  sudo chmod 0644 "${BACKUP_FILE}"
  echo "[backup] ${BACKUP_FILE}"
fi

sudo install -o tank -g tank -m 0644 "${SOURCE_FILE}" "${TARGET_FILE}"

echo "[synced] ${SOURCE_FILE} -> ${TARGET_FILE}"
echo "[note] Restart Tank only if you want already-running sessions to pick up new policy immediately"
