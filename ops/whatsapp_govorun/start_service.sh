#!/usr/bin/env bash
set -euo pipefail

UNIT_NAME="whatsapp-govorun-bridge.service"

sudo systemctl restart "${UNIT_NAME}"
sudo systemctl status "${UNIT_NAME}" --no-pager -n 30
