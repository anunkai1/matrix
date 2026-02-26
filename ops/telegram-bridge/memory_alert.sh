#!/usr/bin/env bash
set -euo pipefail

FAILED_UNIT="${1:-}"
LOG_LINES="${TELEGRAM_MEMORY_ALERT_LOG_LINES:-80}"

if [[ -z "${FAILED_UNIT}" ]]; then
  echo "memory-alert: missing failed unit name" >&2
  exit 2
fi
if ! [[ "${LOG_LINES}" =~ ^[0-9]+$ ]]; then
  echo "memory-alert: TELEGRAM_MEMORY_ALERT_LOG_LINES must be a non-negative integer" >&2
  exit 2
fi

host="$(hostname -s 2>/dev/null || hostname)"
timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "memory-alert: host=${host} ts=${timestamp} failed_unit=${FAILED_UNIT}"

if command -v systemctl >/dev/null 2>&1; then
  systemctl --no-pager --full status "${FAILED_UNIT}" || true
fi

if command -v journalctl >/dev/null 2>&1 && [[ "${LOG_LINES}" -gt 0 ]]; then
  journalctl -u "${FAILED_UNIT}" -n "${LOG_LINES}" --no-pager || true
fi
