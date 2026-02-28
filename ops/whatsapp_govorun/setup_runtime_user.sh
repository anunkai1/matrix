#!/usr/bin/env bash
set -euo pipefail

USER_NAME="wa-govorun"
HOME_DIR="/home/${USER_NAME}"
RUNTIME_ROOT="${HOME_DIR}/whatsapp-govorun"

if id "${USER_NAME}" >/dev/null 2>&1; then
  echo "User ${USER_NAME} already exists"
else
  sudo useradd -m -s /bin/bash "${USER_NAME}"
  echo "Created user ${USER_NAME}"
fi

sudo mkdir -p "${RUNTIME_ROOT}" "${RUNTIME_ROOT}/app" "${RUNTIME_ROOT}/state" "${RUNTIME_ROOT}/backup"
sudo chown -R "${USER_NAME}:${USER_NAME}" "${RUNTIME_ROOT}"

# Keep this user's --user services active across reboot
sudo loginctl enable-linger "${USER_NAME}"

echo "Runtime user setup complete: ${USER_NAME}"
