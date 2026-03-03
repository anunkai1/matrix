#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
WA_UNIT_NAME="whatsapp-govorun-bridge.service"
BRIDGE_UNIT_NAME="govorun-whatsapp-bridge.service"
WA_UNIT_SRC="${REPO_ROOT}/infra/systemd/${WA_UNIT_NAME}"
BRIDGE_UNIT_SRC="${REPO_ROOT}/infra/systemd/${BRIDGE_UNIT_NAME}"
WA_UNIT_DST="/etc/systemd/system/${WA_UNIT_NAME}"
BRIDGE_UNIT_DST="/etc/systemd/system/${BRIDGE_UNIT_NAME}"

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

RUNTIME_USER="$(resolve_runtime_user)"
TMP_WA="$(mktemp)"
TMP_BRIDGE="$(mktemp)"
cleanup() {
  rm -f "${TMP_WA}" "${TMP_BRIDGE}"
}
trap cleanup EXIT

if [[ ! -f "${WA_UNIT_SRC}" ]]; then
  echo "Missing unit template: ${WA_UNIT_SRC}" >&2
  exit 1
fi
if [[ ! -f "${BRIDGE_UNIT_SRC}" ]]; then
  echo "Missing unit template: ${BRIDGE_UNIT_SRC}" >&2
  exit 1
fi

sed \
  -e "s|User=govorun|User=${RUNTIME_USER}|g" \
  -e "s|Group=govorun|Group=${RUNTIME_USER}|g" \
  -e "s|/home/govorun/|/home/${RUNTIME_USER}/|g" \
  "${WA_UNIT_SRC}" > "${TMP_WA}"

sed \
  -e "s|User=govorun|User=${RUNTIME_USER}|g" \
  -e "s|Group=govorun|Group=${RUNTIME_USER}|g" \
  -e "s|/home/govorun/|/home/${RUNTIME_USER}/|g" \
  "${BRIDGE_UNIT_SRC}" > "${TMP_BRIDGE}"

sudo cp "${TMP_WA}" "${WA_UNIT_DST}"
sudo cp "${TMP_BRIDGE}" "${BRIDGE_UNIT_DST}"

sudo systemctl daemon-reload
sudo systemctl enable "${WA_UNIT_NAME}" "${BRIDGE_UNIT_NAME}"

echo "Installed and enabled system services: ${WA_UNIT_NAME}, ${BRIDGE_UNIT_NAME} (user=${RUNTIME_USER})"
