#!/usr/bin/env bash
set -euo pipefail

VENV_PATH="${MAVALI_ETH_VENV:-/home/mavali_eth/.local/share/mavali-eth/venv}"

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo -n "$@"
  fi
}

run_privileged apt-get update
run_privileged apt-get install -y python3-venv

mkdir -p "$(dirname "${VENV_PATH}")"
if [[ ! -x "${VENV_PATH}/bin/python3" ]]; then
  python3 -m venv "${VENV_PATH}"
fi

"${VENV_PATH}/bin/pip" install --upgrade pip wheel
"${VENV_PATH}/bin/pip" install --upgrade eth-account

"${VENV_PATH}/bin/python3" /home/architect/matrix/ops/mavali_eth/eth_account_helper.py create-wallet <<'JSON' >/dev/null
{"passphrase":"validation-passphrase"}
JSON

echo "mavali_eth signing runtime ready at ${VENV_PATH}"
