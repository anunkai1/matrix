#!/usr/bin/env bash
set -euo pipefail

UNIT_NAME="telegram-architect-bridge.service"

sudo systemctl --no-pager --full status "${UNIT_NAME}"
