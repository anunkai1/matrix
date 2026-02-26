#!/usr/bin/env bash
set -euo pipefail

DEFAULT_STATE_DIR="/home/architect/.local/state/telegram-architect-bridge"
DB_PATH="${TELEGRAM_MEMORY_SQLITE_PATH:-${DEFAULT_STATE_DIR}/memory.sqlite3}"
MAX_DB_BYTES="${TELEGRAM_MEMORY_HEALTH_MAX_DB_BYTES:-1073741824}"
MAX_QUERY_MS="${TELEGRAM_MEMORY_HEALTH_MAX_QUERY_MS:-1500}"
LOOKBACK_MINUTES="${TELEGRAM_MEMORY_HEALTH_LOOKBACK_MINUTES:-60}"
MAX_LOCK_ERRORS="${TELEGRAM_MEMORY_HEALTH_MAX_LOCK_ERRORS:-0}"
MAX_WRITE_FAILURES="${TELEGRAM_MEMORY_HEALTH_MAX_WRITE_FAILURES:-0}"

usage() {
  cat <<'EOF'
Usage: memory_health_check.sh [--db <path>]

Checks memory DB size/query health and scans bridge journal logs for lock/write failures.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --db)
      DB_PATH="${2:-}"
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

for var_name in MAX_DB_BYTES MAX_QUERY_MS LOOKBACK_MINUTES MAX_LOCK_ERRORS MAX_WRITE_FAILURES; do
  value="${!var_name}"
  if ! [[ "${value}" =~ ^[0-9]+$ ]]; then
    echo "${var_name} must be a non-negative integer." >&2
    exit 1
  fi
done

if [[ ! -f "${DB_PATH}" ]]; then
  echo "memory-health: fail db_not_found path=${DB_PATH}" >&2
  exit 2
fi
if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "memory-health: fail sqlite3_missing" >&2
  exit 2
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "memory-health: fail python3_missing" >&2
  exit 2
fi
if ! command -v journalctl >/dev/null 2>&1; then
  echo "memory-health: fail journalctl_missing" >&2
  exit 2
fi

db_size_bytes="$(stat -c %s "${DB_PATH}")"
if [[ "${db_size_bytes}" -gt "${MAX_DB_BYTES}" ]]; then
  echo "memory-health: fail db_size_exceeded size_bytes=${db_size_bytes} max_bytes=${MAX_DB_BYTES}" >&2
  exit 2
fi

read -r query_ms message_count fact_count summary_count <<EOF
$(DB_PATH="${DB_PATH}" python3 - <<'PY'
import os
import sqlite3
import time

db_path = os.environ["DB_PATH"]
conn = sqlite3.connect(db_path, timeout=30)
start = time.perf_counter()
message_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
fact_count = conn.execute("SELECT COUNT(*) FROM memory_facts WHERE status = 'active'").fetchone()[0]
summary_count = conn.execute("SELECT COUNT(*) FROM chat_summaries").fetchone()[0]
elapsed_ms = int((time.perf_counter() - start) * 1000)
quick_check = conn.execute("PRAGMA quick_check").fetchone()[0]
conn.close()
if str(quick_check).lower() != "ok":
    raise SystemExit(f"{elapsed_ms} {message_count} {fact_count} {summary_count} quick_check_failed")
print(f"{elapsed_ms} {message_count} {fact_count} {summary_count}")
PY
)
EOF

if [[ "${query_ms}" -gt "${MAX_QUERY_MS}" ]]; then
  echo "memory-health: fail query_too_slow query_ms=${query_ms} max_query_ms=${MAX_QUERY_MS}" >&2
  exit 2
fi

journal_slice="$(journalctl -u telegram-architect-bridge.service --since "-${LOOKBACK_MINUTES} min" --no-pager || true)"
lock_errors="$(printf '%s\n' "${journal_slice}" | grep -Eic 'database is locked|sqlite[^ ]* locked' || true)"
write_failures="$(printf '%s\n' "${journal_slice}" | grep -Eic 'Failed to (finish shared memory turn|prepare shared memory turn|query memory status|clear shared memory session|initialize shared memory|run retention prune)' || true)"

if [[ "${lock_errors}" -gt "${MAX_LOCK_ERRORS}" ]]; then
  echo "memory-health: fail lock_errors lock_errors=${lock_errors} max_lock_errors=${MAX_LOCK_ERRORS} lookback_minutes=${LOOKBACK_MINUTES}" >&2
  exit 2
fi
if [[ "${write_failures}" -gt "${MAX_WRITE_FAILURES}" ]]; then
  echo "memory-health: fail write_failures write_failures=${write_failures} max_write_failures=${MAX_WRITE_FAILURES} lookback_minutes=${LOOKBACK_MINUTES}" >&2
  exit 2
fi

echo "memory-health: ok db_size_bytes=${db_size_bytes} query_ms=${query_ms} messages=${message_count} active_facts=${fact_count} summaries=${summary_count} lock_errors=${lock_errors} write_failures=${write_failures}"
