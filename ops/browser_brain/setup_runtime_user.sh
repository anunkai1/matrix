#!/usr/bin/env bash
set -euo pipefail

USER_NAME="browser_brain"
HOME_DIR="/home/${USER_NAME}"
RUNTIME_ROOT="${HOME_DIR}/browserbrain"
STATE_ROOT="/var/lib/server3-browser-brain"

if id "${USER_NAME}" >/dev/null 2>&1; then
  echo "User ${USER_NAME} already exists"
else
  sudo useradd -m -s /bin/bash "${USER_NAME}"
  echo "Created user ${USER_NAME}"
fi

sudo mkdir -p "${RUNTIME_ROOT}" "${STATE_ROOT}" "${STATE_ROOT}/profile" "${STATE_ROOT}/captures"
sudo chown -R "${USER_NAME}:${USER_NAME}" "${HOME_DIR}" "${STATE_ROOT}"

echo "Runtime user setup complete: ${USER_NAME}"
