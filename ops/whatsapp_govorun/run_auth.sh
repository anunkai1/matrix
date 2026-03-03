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
APP_DIR="/home/${USER_NAME}/whatsapp-govorun/app"
WA_UNIT_NAME="whatsapp-govorun-bridge.service"
BRIDGE_UNIT_NAME="govorun-whatsapp-bridge.service"

if systemctl cat "${BRIDGE_UNIT_NAME}" >/dev/null 2>&1; then
  sudo systemctl stop "${BRIDGE_UNIT_NAME}" || true
fi

if systemctl cat "${WA_UNIT_NAME}" >/dev/null 2>&1; then
  sudo systemctl stop "${WA_UNIT_NAME}" || true
elif sudo -iu "${USER_NAME}" bash -lc "systemctl --user cat '${WA_UNIT_NAME}' >/dev/null 2>&1"; then
  sudo -iu "${USER_NAME}" bash -lc "systemctl --user stop '${WA_UNIT_NAME}' || true"
fi

sudo -iu "${USER_NAME}" bash -lc "cd '${APP_DIR}' && npm run auth"
