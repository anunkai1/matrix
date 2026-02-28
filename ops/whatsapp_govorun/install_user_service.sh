#!/usr/bin/env bash
set -euo pipefail

USER_NAME="wa-govorun"
HOME_DIR="/home/${USER_NAME}"
RUNTIME_ROOT="${HOME_DIR}/whatsapp-govorun"
APP_DIR="${RUNTIME_ROOT}/app"
UNIT_DIR="${HOME_DIR}/.config/systemd/user"
UNIT_NAME="whatsapp-govorun-bridge.service"
UNIT_PATH="${UNIT_DIR}/${UNIT_NAME}"
TARGET_STATE="/home/architect/matrix/infra/systemd/user/whatsapp-govorun-bridge.service.target-state"

sudo -iu "${USER_NAME}" mkdir -p "${UNIT_DIR}"

if [[ ! -f "${TARGET_STATE}" ]]; then
  echo "Missing target state file: ${TARGET_STATE}" >&2
  exit 1
fi

sudo cp "${TARGET_STATE}" "${UNIT_PATH}"

sudo chown "${USER_NAME}:${USER_NAME}" "${UNIT_PATH}"

# Ensure user service manager is active on boot
sudo loginctl enable-linger "${USER_NAME}"

# Reload and enable without starting yet (start after auth)
sudo -iu "${USER_NAME}" bash -lc "systemctl --user daemon-reload && systemctl --user enable '${UNIT_NAME}'"

echo "Installed user service: ${UNIT_NAME}"
