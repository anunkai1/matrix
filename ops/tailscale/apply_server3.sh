#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'HELP'
Usage:
  apply_server3.sh [--auth-key <tskey-...> | --auth-key-file <path>] [--no-nordvpn-compat]

Applies Server3 Tailscale target state:
- installs tailscale (if missing)
- enables/starts tailscaled
- runs tailscale up (interactive URL auth by default, or auth key if provided)
- configures NordVPN allowlist ports needed for Tailscale coexistence
  (443/tcp, 3478/udp, 41641/udp) when nordvpn CLI is present

By default, this script applies NordVPN compatibility handling during login:
- temporarily disable NordVPN Kill Switch and Firewall
- run tailscale up
- restore original NordVPN Kill Switch and Firewall states
HELP
}

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

AUTH_KEY=""
AUTH_KEY_FILE=""
NORD_COMPAT="yes"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --auth-key)
      AUTH_KEY="${2:-}"
      shift 2
      ;;
    --auth-key-file)
      AUTH_KEY_FILE="${2:-}"
      shift 2
      ;;
    --no-nordvpn-compat)
      NORD_COMPAT="no"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[apply_server3] unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -n "$AUTH_KEY" && -n "$AUTH_KEY_FILE" ]]; then
  echo "[apply_server3] use either --auth-key or --auth-key-file, not both" >&2
  exit 2
fi

if [[ -n "$AUTH_KEY_FILE" ]]; then
  if [[ ! -f "$AUTH_KEY_FILE" ]]; then
    echo "[apply_server3] auth key file not found: $AUTH_KEY_FILE" >&2
    exit 2
  fi
  AUTH_KEY="$(<"$AUTH_KEY_FILE")"
fi

if [[ -z "$AUTH_KEY" && -n "${TS_AUTH_KEY:-}" ]]; then
  AUTH_KEY="${TS_AUTH_KEY}"
fi

if ! command -v tailscale >/dev/null 2>&1; then
  run_privileged bash -lc 'curl -fsSL https://tailscale.com/install.sh | sh'
fi

ORIG_NORD_KS=""
ORIG_NORD_FW=""
NORD_MUTATED="no"

restore_nordvpn() {
  if [[ "$NORD_MUTATED" != "yes" ]]; then
    return
  fi
  if [[ "$ORIG_NORD_FW" == "enabled" ]]; then
    run_privileged nordvpn set firewall on >/dev/null 2>&1 || true
  elif [[ "$ORIG_NORD_FW" == "disabled" ]]; then
    run_privileged nordvpn set firewall off >/dev/null 2>&1 || true
  fi

  if [[ "$ORIG_NORD_KS" == "enabled" ]]; then
    run_privileged nordvpn set killswitch on >/dev/null 2>&1 || true
  elif [[ "$ORIG_NORD_KS" == "disabled" ]]; then
    run_privileged nordvpn set killswitch off >/dev/null 2>&1 || true
  fi
}

trap restore_nordvpn EXIT

if [[ "$NORD_COMPAT" == "yes" ]] && command -v nordvpn >/dev/null 2>&1; then
  # Keep coexistence port exceptions persistent in NordVPN policy.
  run_privileged nordvpn allowlist add port 443 protocol TCP >/dev/null 2>&1 || true
  run_privileged nordvpn allowlist add port 3478 protocol UDP >/dev/null 2>&1 || true
  run_privileged nordvpn allowlist add port 41641 protocol UDP >/dev/null 2>&1 || true

  ORIG_NORD_KS="$(run_privileged nordvpn settings | awk -F': ' '/Kill Switch:/{print tolower($2)}')"
  ORIG_NORD_FW="$(run_privileged nordvpn settings | awk -F': ' '/Firewall:/{print tolower($2)}')"
  if [[ "$ORIG_NORD_KS" == "enabled" ]]; then
    run_privileged nordvpn set killswitch off >/dev/null
    NORD_MUTATED="yes"
  fi
  if [[ "$ORIG_NORD_FW" == "enabled" ]]; then
    run_privileged nordvpn set firewall off >/dev/null
    NORD_MUTATED="yes"
  fi
fi

run_privileged systemctl enable --now tailscaled

if [[ -n "$AUTH_KEY" ]]; then
  run_privileged tailscale up --auth-key "$AUTH_KEY"
else
  run_privileged tailscale up --qr=false
fi

echo "[apply_server3] tailscale state"
run_privileged tailscale status
echo "[apply_server3] tailscale ipv4"
run_privileged tailscale ip -4
