#!/usr/bin/env bash
set -euo pipefail

USER_NAME="wa-govorun"
APP_DIR="/home/${USER_NAME}/whatsapp-govorun/app"
UNIT_NAME="whatsapp-govorun-bridge.service"

sudo -iu "${USER_NAME}" bash -lc "systemctl --user stop '${UNIT_NAME}' || true; cd '${APP_DIR}' && npm run auth"
