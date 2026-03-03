#!/usr/bin/env bash
set -euo pipefail

resolve_runtime_user() {
  if [[ -n "${WA_RUNTIME_USER:-}" ]]; then
    echo "${WA_RUNTIME_USER}"
    return
  fi
  if id "govorun" >/dev/null 2>&1; then
    echo "govorun"
    return
  fi
  if id "wa-govorun" >/dev/null 2>&1; then
    echo "wa-govorun"
    return
  fi
  echo "govorun"
}

USER_NAME="$(resolve_runtime_user)"
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
  sudo sed -i \
    -e "s|/home/govorun/|/home/${USER_NAME}/|g" \
    -e "s|/home/wa-govorun/|/home/${USER_NAME}/|g" \
    -e "s|^WA_TRIGGER=.*|WA_TRIGGER=@говорун|" \
    "${APP_DIR}/.env"
  if sudo grep -q "^WA_ALLOW_FROM_ME_GROUP_TRIGGER_ONLY=" "${APP_DIR}/.env"; then
    sudo sed -i "s|^WA_ALLOW_FROM_ME_GROUP_TRIGGER_ONLY=.*|WA_ALLOW_FROM_ME_GROUP_TRIGGER_ONLY=true|" "${APP_DIR}/.env"
  else
    echo "WA_ALLOW_FROM_ME_GROUP_TRIGGER_ONLY=true" | sudo tee -a "${APP_DIR}/.env" >/dev/null
  fi
fi

sudo chown -R "${USER_NAME}:${USER_NAME}" "${RUNTIME_ROOT}"

# Install runtime deps as service user
sudo -iu "${USER_NAME}" bash -lc "cd '${APP_DIR}' && npm install --omit=dev"

echo "Bridge deployed to ${APP_DIR}"
