#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-apply}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNIT_NAMES=(
  "server3-ralph-loop.service"
  "server3-ralph-loop.timer"
  "server3-ralph-daily-report.service"
  "server3-ralph-daily-report.timer"
)

for unit_name in "${UNIT_NAMES[@]}"; do
  if [[ ! -f "${REPO_ROOT}/infra/systemd/${unit_name}" ]]; then
    echo "Missing unit file under ${REPO_ROOT}/infra/systemd: ${unit_name}" >&2
    exit 1
  fi
done

case "${MODE}" in
  apply)
    for unit_name in "${UNIT_NAMES[@]}"; do
      sudo install -m 0644 "${REPO_ROOT}/infra/systemd/${unit_name}" "/etc/systemd/system/${unit_name}"
    done
    sudo systemctl daemon-reload
    sudo systemctl enable --now server3-ralph-loop.timer server3-ralph-daily-report.timer
    echo "Installed and enabled Ralph timers"
    ;;
  rollback)
    for timer_name in server3-ralph-loop.timer server3-ralph-daily-report.timer; do
      if sudo systemctl is-active --quiet "${timer_name}"; then
        sudo systemctl stop "${timer_name}"
      fi
      if sudo systemctl is-enabled --quiet "${timer_name}"; then
        sudo systemctl disable "${timer_name}"
      fi
    done
    for unit_name in "${UNIT_NAMES[@]}"; do
      sudo rm -f "/etc/systemd/system/${unit_name}"
    done
    sudo systemctl daemon-reload
    echo "Removed Ralph loop and daily report units"
    ;;
  *)
    echo "Usage: $0 [apply|rollback]" >&2
    exit 1
    ;;
esac
