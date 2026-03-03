#!/usr/bin/env bash
set -euo pipefail

resolve_runtime_user_for_setup() {
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

USER_NAME="$(resolve_runtime_user_for_setup)"
HOME_DIR="/home/${USER_NAME}"
RUNTIME_ROOT="${HOME_DIR}/whatsapp-govorun"
WORK_ROOT="${HOME_DIR}/govorunbot"
STATE_ROOT="${HOME_DIR}/.local/state/govorun-whatsapp-bridge"

if id "${USER_NAME}" >/dev/null 2>&1; then
  echo "User ${USER_NAME} already exists"
else
  sudo useradd -m -s /bin/bash "${USER_NAME}"
  echo "Created user ${USER_NAME}"
fi

sudo mkdir -p "${RUNTIME_ROOT}" "${RUNTIME_ROOT}/app" "${RUNTIME_ROOT}/state" "${RUNTIME_ROOT}/backup"
sudo mkdir -p "${WORK_ROOT}" "${STATE_ROOT}"
sudo chown -R "${USER_NAME}:${USER_NAME}" "${HOME_DIR}"

echo "Runtime user setup complete: ${USER_NAME}"
