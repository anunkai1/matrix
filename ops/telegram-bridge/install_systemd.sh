#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-apply}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNIT_NAME="telegram-architect-bridge.service"
SOURCE_UNIT="${REPO_ROOT}/infra/systemd/${UNIT_NAME}"
TARGET_UNIT="/etc/systemd/system/${UNIT_NAME}"

if [[ ! -f "${SOURCE_UNIT}" ]]; then
  echo "Unit file not found: ${SOURCE_UNIT}" >&2
  exit 1
fi

case "${MODE}" in
  apply)
    sudo install -m 0644 "${SOURCE_UNIT}" "${TARGET_UNIT}"
    sudo systemctl daemon-reload
    sudo systemctl enable "${UNIT_NAME}"
    echo "Installed and enabled ${UNIT_NAME}"
    ;;
  rollback)
    if sudo systemctl is-active --quiet "${UNIT_NAME}"; then
      sudo systemctl stop "${UNIT_NAME}"
    fi
    if sudo systemctl is-enabled --quiet "${UNIT_NAME}"; then
      sudo systemctl disable "${UNIT_NAME}"
    fi
    if [[ -f "${TARGET_UNIT}" ]]; then
      sudo rm -f "${TARGET_UNIT}"
      echo "Removed ${TARGET_UNIT}"
    fi
    sudo systemctl daemon-reload
    ;;
  *)
    echo "Usage: $0 [apply|rollback]" >&2
    exit 1
    ;;
esac
