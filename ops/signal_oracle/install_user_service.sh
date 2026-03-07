#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TRANSPORT_UNIT="signal-oracle-bridge.service"
BRIDGE_UNIT="oracle-signal-bridge.service"

sudo cp "${REPO_ROOT}/infra/systemd/${TRANSPORT_UNIT}" "/etc/systemd/system/${TRANSPORT_UNIT}"
sudo cp "${REPO_ROOT}/infra/systemd/${BRIDGE_UNIT}" "/etc/systemd/system/${BRIDGE_UNIT}"
sudo systemctl daemon-reload
sudo systemctl enable "${TRANSPORT_UNIT}" "${BRIDGE_UNIT}"

echo "Installed and enabled ${TRANSPORT_UNIT} and ${BRIDGE_UNIT}"
