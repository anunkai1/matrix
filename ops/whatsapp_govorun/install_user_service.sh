#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
WA_UNIT_NAME="whatsapp-govorun-bridge.service"
BRIDGE_UNIT_NAME="govorun-whatsapp-bridge.service"
WA_UNIT_SRC="${REPO_ROOT}/infra/systemd/${WA_UNIT_NAME}"
BRIDGE_UNIT_SRC="${REPO_ROOT}/infra/systemd/${BRIDGE_UNIT_NAME}"
WA_UNIT_DST="/etc/systemd/system/${WA_UNIT_NAME}"
BRIDGE_UNIT_DST="/etc/systemd/system/${BRIDGE_UNIT_NAME}"

if [[ ! -f "${WA_UNIT_SRC}" ]]; then
  echo "Missing unit template: ${WA_UNIT_SRC}" >&2
  exit 1
fi
if [[ ! -f "${BRIDGE_UNIT_SRC}" ]]; then
  echo "Missing unit template: ${BRIDGE_UNIT_SRC}" >&2
  exit 1
fi

sudo cp "${WA_UNIT_SRC}" "${WA_UNIT_DST}"
sudo cp "${BRIDGE_UNIT_SRC}" "${BRIDGE_UNIT_DST}"

sudo systemctl daemon-reload
sudo systemctl enable "${WA_UNIT_NAME}" "${BRIDGE_UNIT_NAME}"

echo "Installed and enabled system services: ${WA_UNIT_NAME}, ${BRIDGE_UNIT_NAME} (user=govorun)"
