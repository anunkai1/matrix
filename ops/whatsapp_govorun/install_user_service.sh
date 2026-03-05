#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
WA_UNIT_NAME="whatsapp-govorun-bridge.service"
BRIDGE_UNIT_NAME="govorun-whatsapp-bridge.service"
CHAT_ROUTING_VALIDATOR="${REPO_ROOT}/ops/chat-routing/validate_chat_routing_contract.py"
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
if [[ ! -f "${CHAT_ROUTING_VALIDATOR}" ]]; then
  echo "Missing contract validator: ${CHAT_ROUTING_VALIDATOR}" >&2
  exit 1
fi

if [[ "${SKIP_CHAT_ROUTING_CONTRACT_CHECK:-0}" != "1" ]]; then
  sudo /usr/bin/python3 "${CHAT_ROUTING_VALIDATOR}"
fi

sudo cp "${WA_UNIT_SRC}" "${WA_UNIT_DST}"
sudo cp "${BRIDGE_UNIT_SRC}" "${BRIDGE_UNIT_DST}"

sudo systemctl daemon-reload
sudo systemctl enable "${WA_UNIT_NAME}" "${BRIDGE_UNIT_NAME}"

echo "Installed and enabled system services: ${WA_UNIT_NAME}, ${BRIDGE_UNIT_NAME} (user=govorun)"
