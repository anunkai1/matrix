#!/usr/bin/env bash
set -euo pipefail

USER_NAME="oracle"
HOME_DIR="/home/${USER_NAME}"
RUNTIME_ROOT="${HOME_DIR}/signal-oracle"
APP_DIR="${RUNTIME_ROOT}/app"
WORK_ROOT="${HOME_DIR}/oraclebot"
STAGE_DIR="$(mktemp -d)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_TEMPLATE="${REPO_ROOT}/infra/env/signal-oracle-bridge.env.example"

cleanup() {
  rm -rf "${STAGE_DIR}"
}
trap cleanup EXIT

sudo mkdir -p "${APP_DIR}" "${RUNTIME_ROOT}/state" "${WORK_ROOT}"
sudo rsync -a "${SCRIPT_DIR}/bridge/" "${APP_DIR}/"

mkdir -p "${STAGE_DIR}/src/telegram_bridge"
rsync -a --delete \
  --exclude "__pycache__" \
  "${REPO_ROOT}/src/telegram_bridge/" "${STAGE_DIR}/src/telegram_bridge/"
: > "${STAGE_DIR}/AGENTS.md"

sudo rsync -a --delete "${STAGE_DIR}/" "${WORK_ROOT}/"

if ! sudo test -f "/etc/default/signal-oracle-bridge"; then
  sudo cp "${ENV_TEMPLATE}" "/etc/default/signal-oracle-bridge"
fi

sudo chown -R "${USER_NAME}:${USER_NAME}" "${RUNTIME_ROOT}" "${WORK_ROOT}"

echo "Deployed Signal transport to ${APP_DIR}"
echo "Deployed minimal Oracle bridge workspace to ${WORK_ROOT}"
