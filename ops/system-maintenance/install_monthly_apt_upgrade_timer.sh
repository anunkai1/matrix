#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-apply}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE_NAME="server3-monthly-apt-upgrade.service"
TIMER_NAME="server3-monthly-apt-upgrade.timer"

SERVICE_SRC="${REPO_ROOT}/infra/systemd/${SERVICE_NAME}"
TIMER_SRC="${REPO_ROOT}/infra/systemd/${TIMER_NAME}"
SERVICE_DST="/etc/systemd/system/${SERVICE_NAME}"
TIMER_DST="/etc/systemd/system/${TIMER_NAME}"

if [[ ! -f "${SERVICE_SRC}" || ! -f "${TIMER_SRC}" ]]; then
  echo "Missing unit file(s) under ${REPO_ROOT}/infra/systemd" >&2
  exit 1
fi

case "${MODE}" in
  apply)
    sudo install -m 0644 "${SERVICE_SRC}" "${SERVICE_DST}"
    sudo install -m 0644 "${TIMER_SRC}" "${TIMER_DST}"
    sudo systemctl daemon-reload
    sudo systemctl enable --now "${TIMER_NAME}"
    echo "Installed and enabled ${TIMER_NAME}"
    ;;
  status)
    sudo systemctl --no-pager --full status "${TIMER_NAME}" "${SERVICE_NAME}"
    ;;
  run-now)
    sudo systemctl start "${SERVICE_NAME}"
    sudo systemctl --no-pager --full status "${SERVICE_NAME}"
    ;;
  rollback)
    if sudo systemctl is-active --quiet "${TIMER_NAME}"; then
      sudo systemctl stop "${TIMER_NAME}"
    fi
    if sudo systemctl is-enabled --quiet "${TIMER_NAME}"; then
      sudo systemctl disable "${TIMER_NAME}"
    fi
    sudo rm -f "${TIMER_DST}" "${SERVICE_DST}"
    sudo systemctl daemon-reload
    echo "Removed ${SERVICE_NAME} and ${TIMER_NAME}"
    ;;
  *)
    echo "Usage: $0 [apply|status|run-now|rollback]" >&2
    exit 1
    ;;
esac

