#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TRANSPORT_UNIT="signal-oracle-bridge.service"
BRIDGE_UNIT="oracle-signal-bridge.service"
RESTART_HELPER="${REPO_ROOT}/ops/telegram-bridge/restart_and_verify.sh"
SUDOERS_DST="/etc/sudoers.d/oracle-signal-bridge"

sudo cp "${REPO_ROOT}/infra/systemd/${TRANSPORT_UNIT}" "/etc/systemd/system/${TRANSPORT_UNIT}"
sudo cp "${REPO_ROOT}/infra/systemd/${BRIDGE_UNIT}" "/etc/systemd/system/${BRIDGE_UNIT}"
sudo systemctl daemon-reload
sudo systemctl enable "${TRANSPORT_UNIT}" "${BRIDGE_UNIT}"

sudo bash -lc "cat > '${SUDOERS_DST}' <<'EOF'
# Mirror of /etc/sudoers.d/oracle-signal-bridge on Server3.
Defaults:oracle !requiretty
oracle ALL=(root) NOPASSWD: ${RESTART_HELPER} --unit ${BRIDGE_UNIT}
EOF"
sudo chmod 440 "${SUDOERS_DST}"
sudo visudo -cf "${SUDOERS_DST}"

echo "Installed and enabled ${TRANSPORT_UNIT} and ${BRIDGE_UNIT}"
