#!/usr/bin/env bash
set -euo pipefail

USER_NAME="govorun"
APP_DIR="/home/${USER_NAME}/whatsapp-govorun/app"
WA_UNIT_NAME="whatsapp-govorun-bridge.service"
BRIDGE_UNIT_NAME="govorun-whatsapp-bridge.service"

sudo systemctl stop "${BRIDGE_UNIT_NAME}" || true
sudo systemctl stop "${WA_UNIT_NAME}" || true
sudo -iu "${USER_NAME}" bash -lc "cd '${APP_DIR}' && npm run auth"
