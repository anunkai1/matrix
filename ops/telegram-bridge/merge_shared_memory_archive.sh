#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEFAULT_STATE_DIR="/home/architect/.local/state/telegram-architect-bridge"
DB_PATH="${TELEGRAM_MEMORY_SQLITE_PATH:-${DEFAULT_STATE_DIR}/memory.sqlite3}"
SHARED_KEY="${TELEGRAM_SHARED_MEMORY_KEY:-}"

usage() {
  cat <<'EOF'
Usage: merge_shared_memory_archive.sh [--db <path>] [--shared-key <key>]

Merges all live shared-session conversation keys (<shared-key>:session:*)
into the configured shared archive key without clearing the live sessions.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --db)
      DB_PATH="${2:-}"
      shift 2
      ;;
    --shared-key)
      SHARED_KEY="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "${DB_PATH}" ]]; then
  echo "Database path is empty." >&2
  exit 1
fi
if [[ -z "${SHARED_KEY}" ]]; then
  echo "TELEGRAM_SHARED_MEMORY_KEY is empty; nothing to merge." >&2
  exit 1
fi
if [[ ! -f "${DB_PATH}" ]]; then
  echo "Memory database not found: ${DB_PATH}" >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but not installed." >&2
  exit 1
fi

python3 "${REPO_ROOT}/ops/telegram-bridge/merge_shared_memory_archive.py" \
  --db "${DB_PATH}" \
  --shared-key "${SHARED_KEY}"
