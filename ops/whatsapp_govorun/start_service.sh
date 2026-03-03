#!/usr/bin/env bash
set -euo pipefail

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

USER_NAME="$(resolve_runtime_user)"
UNIT_NAME="whatsapp-govorun-bridge.service"

if systemctl cat "${UNIT_NAME}" >/dev/null 2>&1; then
  sudo systemctl restart "${UNIT_NAME}"
  sudo systemctl status "${UNIT_NAME}" --no-pager -n 30
  exit 0
fi

if sudo -iu "${USER_NAME}" bash -lc "systemctl --user cat '${UNIT_NAME}' >/dev/null 2>&1"; then
  sudo -iu "${USER_NAME}" bash -lc "systemctl --user restart '${UNIT_NAME}' && systemctl --user status '${UNIT_NAME}' --no-pager -n 30"
  exit 0
fi

echo "Service not found: ${UNIT_NAME} (system or user scope)." >&2
exit 1
