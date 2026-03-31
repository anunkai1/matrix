#!/usr/bin/env bash
set -euo pipefail

TOKEN_DIR="/home/architect/.config/server3-control-plane"
TOKEN_FILE="${TOKEN_DIR}/operator_token"
TOKEN_OWNER="architect"

if [[ "$(id -un)" == "${TOKEN_OWNER}" ]]; then
  mkdir -p "${TOKEN_DIR}"
  chmod 700 "${TOKEN_DIR}"
  if [[ ! -s "${TOKEN_FILE}" ]]; then
    umask 077
    openssl rand -hex 24 > "${TOKEN_FILE}"
  fi
  chmod 600 "${TOKEN_FILE}"
else
  sudo -u "${TOKEN_OWNER}" mkdir -p "${TOKEN_DIR}"
  sudo -u "${TOKEN_OWNER}" chmod 700 "${TOKEN_DIR}"
  if ! sudo -u "${TOKEN_OWNER}" test -s "${TOKEN_FILE}"; then
    sudo -u "${TOKEN_OWNER}" bash -lc "umask 077 && openssl rand -hex 24 > '${TOKEN_FILE}'"
  fi
  sudo -u "${TOKEN_OWNER}" chmod 600 "${TOKEN_FILE}"
fi

echo "${TOKEN_FILE}"
