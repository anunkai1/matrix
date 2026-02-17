#!/usr/bin/env bash
set -euo pipefail

UNIT_NAME="telegram-architect-bridge.service"

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo -n "$@"
  fi
}

run_privileged systemctl restart "${UNIT_NAME}"
run_privileged systemctl --no-pager --full status "${UNIT_NAME}"
