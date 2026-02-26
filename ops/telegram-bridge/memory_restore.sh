#!/usr/bin/env bash
set -euo pipefail

DEFAULT_STATE_DIR="/home/architect/.local/state/telegram-architect-bridge"
TARGET_DB="${TELEGRAM_MEMORY_SQLITE_PATH:-${DEFAULT_STATE_DIR}/memory.sqlite3}"
BACKUP_PATH=""

usage() {
  cat <<'EOF'
Usage: memory_restore.sh <backup_path> [--db <path>]

Restores a SQLite backup into the target memory DB path.
Run this while telegram-architect-bridge.service is stopped.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -eq 0 ]]; then
  usage >&2
  exit 1
fi

BACKUP_PATH="$1"
shift

while [[ $# -gt 0 ]]; do
  case "$1" in
    --db)
      TARGET_DB="${2:-}"
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

if [[ -z "${BACKUP_PATH}" ]]; then
  echo "Backup path is empty." >&2
  exit 1
fi
if [[ ! -f "${BACKUP_PATH}" ]]; then
  echo "Backup file not found: ${BACKUP_PATH}" >&2
  exit 1
fi
if [[ -z "${TARGET_DB}" ]]; then
  echo "Target DB path is empty." >&2
  exit 1
fi
if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "sqlite3 is required but not installed." >&2
  exit 1
fi

mkdir -p "$(dirname "${TARGET_DB}")"

timestamp="$(date +%Y%m%d-%H%M%S)"
if [[ -f "${TARGET_DB}" ]]; then
  pre_restore_backup="${TARGET_DB}.pre-restore.${timestamp}.sqlite3"
  sqlite3 "${TARGET_DB}" ".timeout 5000" ".backup '${pre_restore_backup}'"
  echo "Pre-restore backup: ${pre_restore_backup}"
fi

tmp_target="${TARGET_DB}.restore.${timestamp}.tmp"
cp "${BACKUP_PATH}" "${tmp_target}"
integrity="$(sqlite3 "${tmp_target}" "PRAGMA integrity_check;" | tail -n 1 | tr -d '\r')"
if [[ "${integrity}" != "ok" ]]; then
  rm -f "${tmp_target}"
  echo "Restore source integrity check failed: ${integrity}" >&2
  exit 1
fi

mv "${tmp_target}" "${TARGET_DB}"
rm -f "${TARGET_DB}-wal" "${TARGET_DB}-shm"
chmod 600 "${TARGET_DB}" || true

echo "Restore complete: ${TARGET_DB}"
echo "Source backup: ${BACKUP_PATH}"
