#!/usr/bin/env bash
set -euo pipefail

USER_NAME="govorun"
HOME_DIR="/home/${USER_NAME}"
RUNTIME_ROOT="${HOME_DIR}/whatsapp-govorun"
APP_DIR="${RUNTIME_ROOT}/app"
BRIDGE_ROOT="${HOME_DIR}/govorunbot"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="${SCRIPT_DIR}/bridge"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_TEMPLATE="${REPO_ROOT}/infra/env/whatsapp-govorun-bridge.env.example"

sudo mkdir -p "${APP_DIR}" "${RUNTIME_ROOT}/state" "${RUNTIME_ROOT}/state/logs" "${BRIDGE_ROOT}"

# Sync code while preserving live runtime env.
sudo rsync -a --delete --exclude ".env" "${SRC_DIR}/" "${APP_DIR}/"

# Seed env file once
if ! sudo test -f "${APP_DIR}/.env"; then
  sudo cp "${ENV_TEMPLATE}" "${APP_DIR}/.env"
fi

sudo /usr/bin/python3 "${REPO_ROOT}/ops/runtime_overlays/sync_server3_runtime_overlays.py" --runtime "Govorun bridge"

sudo chown -R "${USER_NAME}:${USER_NAME}" "${RUNTIME_ROOT}" "${BRIDGE_ROOT}"

# Install runtime deps as service user
sudo -iu "${USER_NAME}" bash -lc "cd '${APP_DIR}' && npm install --omit=dev"

echo "Bridge deployed to ${APP_DIR}"
echo "Synced shared-core Govorun bridge overlay to ${BRIDGE_ROOT}"
