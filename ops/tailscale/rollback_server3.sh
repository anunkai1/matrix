#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'HELP'
Usage:
  rollback_server3.sh [--remove-packages]

Connectivity-first rollback for Server3 Tailscale rollout:
- tailscale logout
- disable and stop tailscaled

Optional:
- remove tailscale packages and apt source artifacts
HELP
}

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

REMOVE_PACKAGES="no"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remove-packages)
      REMOVE_PACKAGES="yes"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[rollback_server3] unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! command -v tailscale >/dev/null 2>&1; then
  echo "[rollback_server3] tailscale CLI not installed"
  exit 0
fi

run_privileged tailscale logout || true
run_privileged systemctl disable --now tailscaled || true

if [[ "$REMOVE_PACKAGES" == "yes" ]]; then
  run_privileged apt-get remove -y tailscale tailscale-archive-keyring
  run_privileged rm -f /etc/apt/sources.list.d/tailscale.list
  run_privileged rm -f /usr/share/keyrings/tailscale-archive-keyring.gpg
  run_privileged apt-get update
fi

echo "[rollback_server3] tailscaled state"
run_privileged systemctl is-enabled tailscaled 2>/dev/null || true
run_privileged systemctl is-active tailscaled 2>/dev/null || true
