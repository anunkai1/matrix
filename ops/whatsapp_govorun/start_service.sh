#!/usr/bin/env bash
set -euo pipefail

USER_NAME="wa-govorun"
UNIT_NAME="whatsapp-govorun-bridge.service"

sudo -iu "${USER_NAME}" bash -lc "systemctl --user restart '${UNIT_NAME}' && systemctl --user status '${UNIT_NAME}' --no-pager -n 30"
