#!/usr/bin/env bash
set -euo pipefail

USER_NAME="browser_brain"
VENV_PATH="/var/lib/server3-browser-brain/venv"

if ! id "${USER_NAME}" >/dev/null 2>&1; then
  echo "Missing runtime user ${USER_NAME}. Run ops/browser_brain/setup_runtime_user.sh first." >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y python3-venv

sudo install -d -m 0755 -o "${USER_NAME}" -g "${USER_NAME}" /var/lib/server3-browser-brain

if [[ ! -x "${VENV_PATH}/bin/python3" ]]; then
  sudo -u "${USER_NAME}" python3 -m venv "${VENV_PATH}"
fi

sudo -u "${USER_NAME}" "${VENV_PATH}/bin/pip" install --upgrade pip wheel
sudo -u "${USER_NAME}" "${VENV_PATH}/bin/pip" install --upgrade playwright

echo "browser brain runtime venv ready at ${VENV_PATH}"
