#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
UNIT_NAME="server3-browser-brain.service"
UNIT_SRC="${REPO_ROOT}/infra/systemd/${UNIT_NAME}"
UNIT_DST="/etc/systemd/system/${UNIT_NAME}"
ENV_SRC="${REPO_ROOT}/infra/env/server3-browser-brain.env.example"
ENV_DST="/etc/default/server3-browser-brain"

if [[ ! -f "${UNIT_SRC}" ]]; then
  echo "Missing unit template: ${UNIT_SRC}" >&2
  exit 1
fi

sudo cp "${UNIT_SRC}" "${UNIT_DST}"
if [[ ! -f "${ENV_DST}" ]]; then
  sudo cp "${ENV_SRC}" "${ENV_DST}"
  sudo chmod 600 "${ENV_DST}"
  sudo chown root:root "${ENV_DST}"
fi

sudo systemctl daemon-reload
sudo systemctl enable "${UNIT_NAME}"

echo "Installed and enabled system service: ${UNIT_NAME} (user=browser_brain)"
