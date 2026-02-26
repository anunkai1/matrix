#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_STATE_DIR="/home/architect/.local/state/telegram-architect-bridge"
DB_PATH="${TELEGRAM_MEMORY_SQLITE_PATH:-${DEFAULT_STATE_DIR}/memory.sqlite3}"
BACKUP_DIR="$(dirname "${DB_PATH}")/backups"
BACKUP_PATH=""
KEEP_TEMP=0

usage() {
  cat <<'EOF'
Usage: memory_restore_drill.sh [--backup <path>] [--db <path>] [--keep-temp]

Runs a non-destructive restore drill using a temporary copy of the live DB.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backup)
      BACKUP_PATH="${2:-}"
      shift 2
      ;;
    --db)
      DB_PATH="${2:-}"
      BACKUP_DIR="$(dirname "${DB_PATH}")/backups"
      shift 2
      ;;
    --keep-temp)
      KEEP_TEMP=1
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

if [[ ! -f "${DB_PATH}" ]]; then
  echo "Live DB not found: ${DB_PATH}" >&2
  exit 1
fi

if [[ -z "${BACKUP_PATH}" ]]; then
  latest_backup="$(ls -1t "${BACKUP_DIR}"/memory-*.sqlite3 2>/dev/null | head -n 1 || true)"
  BACKUP_PATH="${latest_backup}"
fi

if [[ -z "${BACKUP_PATH}" || ! -f "${BACKUP_PATH}" ]]; then
  echo "Backup file not found for drill. Provide --backup <path>." >&2
  exit 1
fi

tmpdir="$(mktemp -d)"
cleanup() {
  if [[ "${KEEP_TEMP}" -eq 0 ]]; then
    rm -rf "${tmpdir}"
  fi
}
trap cleanup EXIT

tmp_db="${tmpdir}/memory.sqlite3"
cp "${DB_PATH}" "${tmp_db}"

bash "${SCRIPT_DIR}/memory_restore.sh" "${BACKUP_PATH}" --db "${tmp_db}" >/dev/null
integrity="$(sqlite3 "${tmp_db}" "PRAGMA integrity_check;" | tail -n 1 | tr -d '\r')"
if [[ "${integrity}" != "ok" ]]; then
  echo "Restore drill failed integrity check: ${integrity}" >&2
  exit 1
fi

echo "Restore drill passed."
echo "Backup used: ${BACKUP_PATH}"
echo "Temp DB path: ${tmp_db}"
if [[ "${KEEP_TEMP}" -eq 1 ]]; then
  echo "Temp directory preserved: ${tmpdir}"
fi
