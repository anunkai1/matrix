#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEFAULT_STATE_DIR="/home/architect/.local/state/telegram-architect-bridge"
DB_PATH="${TELEGRAM_MEMORY_SQLITE_PATH:-${DEFAULT_STATE_DIR}/memory.sqlite3}"
BACKUP_DIR=""
RUN_VACUUM=1

usage() {
  cat <<'EOF'
Usage: memory_maintenance.sh [--db <path>] [--backup-dir <dir>] [--skip-vacuum]

Creates a consistent SQLite backup, runs forced retention pruning, and optionally VACUUM.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --db)
      DB_PATH="${2:-}"
      shift 2
      ;;
    --backup-dir)
      BACKUP_DIR="${2:-}"
      shift 2
      ;;
    --skip-vacuum)
      RUN_VACUUM=0
      shift
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
if [[ ! -f "${DB_PATH}" ]]; then
  echo "Memory database not found: ${DB_PATH}" >&2
  exit 1
fi
if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "sqlite3 is required but not installed." >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but not installed." >&2
  exit 1
fi

if [[ -z "${BACKUP_DIR}" ]]; then
  BACKUP_DIR="$(dirname "${DB_PATH}")/backups"
fi
mkdir -p "${BACKUP_DIR}"

timestamp="$(date +%Y%m%d-%H%M%S)"
backup_path="${BACKUP_DIR}/memory-${timestamp}.sqlite3"

sqlite3 "${DB_PATH}" ".timeout 5000" ".backup '${backup_path}'"
integrity="$(sqlite3 "${backup_path}" "PRAGMA integrity_check;" | tail -n 1 | tr -d '\r')"
if [[ "${integrity}" != "ok" ]]; then
  echo "Backup integrity check failed for ${backup_path}: ${integrity}" >&2
  exit 1
fi

echo "Backup created: ${backup_path}"

export MATRIX_REPO_ROOT="${REPO_ROOT}"
export MATRIX_MEMORY_DB_PATH="${DB_PATH}"
export MATRIX_MEMORY_MAX_MESSAGES_PER_KEY="${TELEGRAM_MEMORY_MAX_MESSAGES_PER_KEY:-4000}"
export MATRIX_MEMORY_MAX_SUMMARIES_PER_KEY="${TELEGRAM_MEMORY_MAX_SUMMARIES_PER_KEY:-80}"
export MATRIX_MEMORY_PRUNE_INTERVAL_SECONDS="${TELEGRAM_MEMORY_PRUNE_INTERVAL_SECONDS:-300}"

python3 - <<'PY'
import os
import sys
from pathlib import Path

repo_root = Path(os.environ["MATRIX_REPO_ROOT"])
sys.path.insert(0, str(repo_root / "src" / "telegram_bridge"))

from memory_engine import MemoryEngine  # type: ignore

engine = MemoryEngine(
    os.environ["MATRIX_MEMORY_DB_PATH"],
    max_messages_per_key=int(os.environ["MATRIX_MEMORY_MAX_MESSAGES_PER_KEY"]),
    max_summaries_per_key=int(os.environ["MATRIX_MEMORY_MAX_SUMMARIES_PER_KEY"]),
    prune_interval_seconds=int(os.environ["MATRIX_MEMORY_PRUNE_INTERVAL_SECONDS"]),
)
result = engine.run_retention_prune(force=True)
print(
    "Retention prune complete: "
    f"keys={result.scanned_keys} "
    f"messages={result.pruned_messages} "
    f"summaries={result.pruned_summaries}"
)
PY

if [[ "${RUN_VACUUM}" -eq 1 ]]; then
  python3 - <<'PY'
import os
import sys
from pathlib import Path

repo_root = Path(os.environ["MATRIX_REPO_ROOT"])
sys.path.insert(0, str(repo_root / "src" / "telegram_bridge"))

from memory_engine import MemoryEngine  # type: ignore

engine = MemoryEngine(
    os.environ["MATRIX_MEMORY_DB_PATH"],
    max_messages_per_key=int(os.environ["MATRIX_MEMORY_MAX_MESSAGES_PER_KEY"]),
    max_summaries_per_key=int(os.environ["MATRIX_MEMORY_MAX_SUMMARIES_PER_KEY"]),
    prune_interval_seconds=int(os.environ["MATRIX_MEMORY_PRUNE_INTERVAL_SECONDS"]),
)
engine.checkpoint_and_vacuum()
print("Checkpoint/VACUUM complete.")
PY
fi

echo "Maintenance completed for ${DB_PATH}"
