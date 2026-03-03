#!/usr/bin/env bash
set -euo pipefail

USER_NAME="govorun"
APP_DIR="/home/${USER_NAME}/whatsapp-govorun/app"
WA_UNIT_NAME="whatsapp-govorun-bridge.service"
BRIDGE_UNIT_NAME="govorun-whatsapp-bridge.service"

if systemctl cat "${BRIDGE_UNIT_NAME}" >/dev/null 2>&1; then
  sudo systemctl stop "${BRIDGE_UNIT_NAME}" || true
fi

if systemctl cat "${WA_UNIT_NAME}" >/dev/null 2>&1; then
  sudo systemctl stop "${WA_UNIT_NAME}" || true
fi

sudo -iu "${USER_NAME}" bash -lc "cd '${APP_DIR}' && npm run auth"
