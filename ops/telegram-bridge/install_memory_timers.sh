#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-apply}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNIT_DIR="/etc/systemd/system"

UNITS=(
  "telegram-architect-memory-maintenance.service"
  "telegram-architect-memory-maintenance.timer"
  "telegram-architect-memory-health.service"
  "telegram-architect-memory-health.timer"
)

TIMERS=(
  "telegram-architect-memory-maintenance.timer"
  "telegram-architect-memory-health.timer"
)

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo -n "$@"
  fi
}

case "${MODE}" in
  apply)
    for unit in "${UNITS[@]}"; do
      src="${REPO_ROOT}/infra/systemd/${unit}"
      if [[ ! -f "${src}" ]]; then
        echo "Unit file not found: ${src}" >&2
        exit 1
      fi
      run_privileged install -m 0644 "${src}" "${UNIT_DIR}/${unit}"
      echo "Installed ${UNIT_DIR}/${unit}"
    done
    run_privileged systemctl daemon-reload
    run_privileged systemctl enable --now "${TIMERS[@]}"
    run_privileged systemctl --no-pager --full status "${TIMERS[@]}"
    ;;
  rollback)
    run_privileged systemctl disable --now "${TIMERS[@]}" || true
    for unit in "${UNITS[@]}"; do
      target="${UNIT_DIR}/${unit}"
      if [[ -f "${target}" ]]; then
        run_privileged rm -f "${target}"
        echo "Removed ${target}"
      fi
    done
    run_privileged systemctl daemon-reload
    ;;
  status)
    run_privileged systemctl --no-pager --full status "${TIMERS[@]}"
    ;;
  *)
    echo "Usage: $0 [apply|rollback|status]" >&2
    exit 1
    ;;
esac
