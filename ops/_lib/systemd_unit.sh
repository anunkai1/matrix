#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <action> <unit> [extra args...]" >&2
  exit 1
fi

ACTION="$1"
UNIT_NAME="$2"
shift 2

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo -n "$@"
  fi
}

case "${ACTION}" in
  restart)
    run_privileged systemctl restart "${UNIT_NAME}"
    run_privileged systemctl --no-pager --full status "${UNIT_NAME}" "$@"
    ;;
  status)
    run_privileged systemctl --no-pager --full status "${UNIT_NAME}" "$@"
    ;;
  *)
    echo "Unsupported action: ${ACTION}" >&2
    exit 1
    ;;
esac
