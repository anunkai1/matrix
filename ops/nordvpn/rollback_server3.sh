#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'HELP'
Usage:
  rollback_server3.sh

Immediate connectivity-first rollback for Server3 NordVPN rollout:
- autoconnect off
- killswitch off
- disconnect

This rollback keeps the package installed and leaves subnet allowlist as-is.
Tailscale coexistence allowlisted ports are also left as-is.
HELP
}

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if ! command -v nordvpn >/dev/null 2>&1; then
  echo "[rollback_server3] nordvpn CLI is not installed" >&2
  exit 2
fi

run_privileged nordvpn set autoconnect off
run_privileged nordvpn set killswitch off
run_privileged nordvpn disconnect || true

echo "[rollback_server3] current status"
run_privileged nordvpn status || true
echo "[rollback_server3] current settings"
run_privileged nordvpn settings
