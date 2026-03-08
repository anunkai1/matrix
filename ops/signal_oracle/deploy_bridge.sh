#!/usr/bin/env bash
set -euo pipefail

USER_NAME="oracle"
HOME_DIR="/home/${USER_NAME}"
RUNTIME_ROOT="${HOME_DIR}/signal-oracle"
APP_DIR="${RUNTIME_ROOT}/app"
WORK_ROOT="${HOME_DIR}/oraclebot"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_TEMPLATE="${REPO_ROOT}/infra/env/signal-oracle-bridge.env.example"

sudo mkdir -p "${APP_DIR}" "${RUNTIME_ROOT}/state" "${WORK_ROOT}"
sudo rsync -a "${SCRIPT_DIR}/bridge/" "${APP_DIR}/"

if ! sudo test -f "/etc/default/signal-oracle-bridge"; then
  sudo cp "${ENV_TEMPLATE}" "/etc/default/signal-oracle-bridge"
fi

sudo /usr/bin/python3 "${REPO_ROOT}/ops/runtime_overlays/sync_server3_runtime_overlays.py" --runtime "Oracle bridge"

sudo chown -R "${USER_NAME}:${USER_NAME}" "${RUNTIME_ROOT}" "${WORK_ROOT}"

echo "Deployed Signal transport to ${APP_DIR}"
echo "Synced shared-core Oracle bridge overlay to ${WORK_ROOT}"
