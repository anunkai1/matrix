#!/usr/bin/env bash
set -euo pipefail

SRC_USER="architect"
DST_USER="wa-govorun"
SRC_DIR="/home/${SRC_USER}/.codex"
DST_DIR="/home/${DST_USER}/.codex"

if [[ ! -f "${SRC_DIR}/auth.json" ]]; then
  echo "Missing source auth file: ${SRC_DIR}/auth.json" >&2
  exit 1
fi

sudo mkdir -p "${DST_DIR}"

# Copy minimum required auth/config artifacts.
sudo cp "${SRC_DIR}/auth.json" "${DST_DIR}/auth.json"
if [[ -f "${SRC_DIR}/config.toml" ]]; then
  sudo cp "${SRC_DIR}/config.toml" "${DST_DIR}/config.toml"
fi
if [[ -f "${SRC_DIR}/version.json" ]]; then
  sudo cp "${SRC_DIR}/version.json" "${DST_DIR}/version.json"
fi

sudo chown -R "${DST_USER}:${DST_USER}" "${DST_DIR}"
sudo chmod 700 "${DST_DIR}"
sudo chmod 600 "${DST_DIR}/auth.json"
[[ -f "${DST_DIR}/config.toml" ]] && sudo chmod 600 "${DST_DIR}/config.toml"
[[ -f "${DST_DIR}/version.json" ]] && sudo chmod 644 "${DST_DIR}/version.json"

echo "Synced Codex auth to ${DST_USER}"
