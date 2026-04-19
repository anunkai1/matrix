#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-apply}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE_NAME="signaltube-lab-overnight.service"
RESCAN_SERVICE_NAME="signaltube-lab-rescan.service"
TIMER_NAME="signaltube-lab-overnight.timer"
ENV_NAME="signaltube-lab"

SERVICE_SRC="${REPO_ROOT}/infra/systemd/${SERVICE_NAME}"
RESCAN_SERVICE_SRC="${REPO_ROOT}/infra/systemd/${RESCAN_SERVICE_NAME}"
TIMER_SRC="${REPO_ROOT}/infra/systemd/${TIMER_NAME}"
ENV_SRC="${REPO_ROOT}/infra/env/${ENV_NAME}.env.example"

SERVICE_DST="/etc/systemd/system/${SERVICE_NAME}"
RESCAN_SERVICE_DST="/etc/systemd/system/${RESCAN_SERVICE_NAME}"
TIMER_DST="/etc/systemd/system/${TIMER_NAME}"
ENV_DST="/etc/default/${ENV_NAME}"

if [[ ! -f "${SERVICE_SRC}" || ! -f "${RESCAN_SERVICE_SRC}" || ! -f "${TIMER_SRC}" || ! -f "${ENV_SRC}" ]]; then
  echo "Missing SignalTube overnight collector files under ${REPO_ROOT}" >&2
  exit 1
fi

case "${MODE}" in
  apply)
    sudo install -m 0644 "${SERVICE_SRC}" "${SERVICE_DST}"
    sudo install -m 0644 "${RESCAN_SERVICE_SRC}" "${RESCAN_SERVICE_DST}"
    sudo install -m 0644 "${TIMER_SRC}" "${TIMER_DST}"
    if [[ ! -f "${ENV_DST}" ]]; then
      sudo install -m 0644 "${ENV_SRC}" "${ENV_DST}"
      echo "Created ${ENV_DST} from template."
    fi
    sudo systemctl daemon-reload
    sudo systemctl enable --now "${TIMER_NAME}"
    echo "Installed and enabled ${TIMER_NAME}"
    ;;
  status)
    sudo systemctl --no-pager --full status "${TIMER_NAME}" "${SERVICE_NAME}" "${RESCAN_SERVICE_NAME}"
    ;;
  run-now)
    sudo systemctl start "${RESCAN_SERVICE_NAME}"
    sudo systemctl --no-pager --full status "${RESCAN_SERVICE_NAME}"
    ;;
  rollback)
    if sudo systemctl is-active --quiet "${TIMER_NAME}"; then
      sudo systemctl stop "${TIMER_NAME}"
    fi
    if sudo systemctl is-enabled --quiet "${TIMER_NAME}"; then
      sudo systemctl disable "${TIMER_NAME}"
    fi
    sudo rm -f "${TIMER_DST}" "${SERVICE_DST}" "${RESCAN_SERVICE_DST}"
    sudo systemctl daemon-reload
    echo "Removed ${SERVICE_NAME} and ${TIMER_NAME}"
    ;;
  *)
    echo "Usage: $0 [apply|status|run-now|rollback]" >&2
    exit 1
    ;;
esac
