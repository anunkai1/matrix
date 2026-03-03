#!/usr/bin/env bash
set -euo pipefail

USER_NAME="govorun"
ROOT="/home/${USER_NAME}/whatsapp-govorun"
STATE_DIR="${ROOT}/state"
BACKUP_DIR="${ROOT}/backup"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="${BACKUP_DIR}/state-${STAMP}.tar.gz"

sudo -iu "${USER_NAME}" mkdir -p "${BACKUP_DIR}"

sudo tar -C "${ROOT}" -czf "${OUT}" state
sudo chown "${USER_NAME}:${USER_NAME}" "${OUT}"

echo "Created backup: ${OUT}"

# Keep latest 7 daily snapshots (simple retention)
ls -1t "${BACKUP_DIR}"/state-*.tar.gz 2>/dev/null | tail -n +8 | xargs -r sudo rm -f
