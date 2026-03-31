#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNIT_NAME="server3-control-plane.service"
SRC_UNIT="${REPO_ROOT}/infra/systemd/${UNIT_NAME}"
DST_UNIT="/etc/systemd/system/${UNIT_NAME}"

sudo install -m 0644 "${SRC_UNIT}" "${DST_UNIT}"
sudo systemctl daemon-reload
sudo systemctl enable --now "${UNIT_NAME}"
sudo systemctl --no-pager --full status "${UNIT_NAME}"
