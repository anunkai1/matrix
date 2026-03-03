#!/usr/bin/env bash
set -euo pipefail

USER_NAME="govorun"
HOME_DIR="/home/${USER_NAME}"
RUNTIME_ROOT="${HOME_DIR}/whatsapp-govorun"
APP_DIR="${RUNTIME_ROOT}/app"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="${SCRIPT_DIR}/bridge"

sudo mkdir -p "${APP_DIR}" "${RUNTIME_ROOT}/state" "${RUNTIME_ROOT}/state/logs"

# Sync code while preserving live runtime env.
sudo rsync -a --delete --exclude ".env" "${SRC_DIR}/" "${APP_DIR}/"

# Seed env file once
if ! sudo test -f "${APP_DIR}/.env"; then
  sudo cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
fi

sudo chown -R "${USER_NAME}:${USER_NAME}" "${RUNTIME_ROOT}"

# Install runtime deps as service user
sudo -iu "${USER_NAME}" bash -lc "cd '${APP_DIR}' && npm install --omit=dev"

echo "Bridge deployed to ${APP_DIR}"
