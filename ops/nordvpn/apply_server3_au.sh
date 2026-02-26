#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'HELP'
Usage:
  apply_server3_au.sh [--profile strict|online-recovery]

Applies the Server3 NordVPN target state:
- technology nordlynx
- allowlist subnet 192.168.0.0/24
- allowlist ports for Tailscale coexistence (443/tcp, 3478/udp, 41641/udp)
- connect to au
- autoconnect on
- profile strict: killswitch on + firewall on
- profile online-recovery: killswitch off + firewall off

This script assumes you are already logged in:
  nordvpn login --token <token>
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

PROFILE="online-recovery"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      PROFILE="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[apply_server3_au] unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$PROFILE" != "strict" && "$PROFILE" != "online-recovery" ]]; then
  echo "[apply_server3_au] invalid --profile: $PROFILE (expected strict|online-recovery)" >&2
  exit 2
fi

if ! command -v nordvpn >/dev/null 2>&1; then
  echo "[apply_server3_au] nordvpn CLI is not installed" >&2
  exit 2
fi

if ! run_privileged nordvpn account >/dev/null 2>&1; then
  echo "[apply_server3_au] not logged in; run: nordvpn login --token <token>" >&2
  exit 2
fi

run_privileged nordvpn set technology nordlynx || true
run_privileged nordvpn set lan-discovery off || true
run_privileged nordvpn allowlist add subnet 192.168.0.0/24 || true
run_privileged nordvpn allowlist add port 443 protocol TCP || true
run_privileged nordvpn allowlist add port 3478 protocol UDP || true
run_privileged nordvpn allowlist add port 41641 protocol UDP || true
run_privileged nordvpn connect au
run_privileged nordvpn set autoconnect on || true
CURRENT_FW="$(run_privileged nordvpn settings | awk -F': ' '/Firewall:/{print tolower($2)}')"
if [[ "$PROFILE" == "strict" ]]; then
  run_privileged nordvpn set firewall on || true
  run_privileged nordvpn set killswitch on || true
else
  if [[ "$CURRENT_FW" == "enabled" ]]; then
    run_privileged nordvpn set killswitch off || true
  fi
  run_privileged nordvpn set firewall off || true
fi

echo "[apply_server3_au] final status"
run_privileged nordvpn status
echo "[apply_server3_au] final settings"
run_privileged nordvpn settings
