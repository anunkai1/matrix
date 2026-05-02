#!/usr/bin/env bash
set -euo pipefail

UNIT_NAME="${UNIT_NAME:-telegram-architect-bridge.service}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/../_lib/systemd_unit.sh" restart "${UNIT_NAME}"
