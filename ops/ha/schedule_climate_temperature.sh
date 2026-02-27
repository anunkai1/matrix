#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SET_SCRIPT="$SCRIPT_DIR/set_climate_temperature.sh"
DEFAULT_ENV_FILE="${HA_OPS_ENV_FILE:-/etc/default/ha-ops}"

if [[ "$(id -u)" -ne 0 ]]; then
  has_env_file="false"
  for arg in "$@"; do
    if [[ "$arg" == "--env-file" ]]; then
      has_env_file="true"
      break
    fi
  done
  if [[ "$has_env_file" == "true" ]]; then
    exec sudo -n "$0" "$@"
  fi
  exec sudo -n "$0" --env-file "$DEFAULT_ENV_FILE" "$@"
fi

usage() {
  cat <<'EOF'
Usage:
  schedule_climate_temperature.sh --delay 2h --entity climate.entity_id --temperature 25 [options]

Options:
  --env-file PATH     Env file consumed by set_climate_temperature.sh
                      (default: /etc/default/ha-ops)
  --unit-prefix NAME  Prefix for transient systemd unit names
                      (default: ha-climate-temp)
  --dry-run           Schedule a dry-run execution (no Home Assistant write)
  -h, --help          Show this help text
EOF
}

delay=""
entity=""
temperature=""
env_file="$DEFAULT_ENV_FILE"
unit_prefix="ha-climate-temp"
dry_run="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --delay)
      delay="${2:-}"
      shift 2
      ;;
    --entity)
      entity="${2:-}"
      shift 2
      ;;
    --temperature)
      temperature="${2:-}"
      shift 2
      ;;
    --env-file)
      env_file="${2:-}"
      shift 2
      ;;
    --unit-prefix)
      unit_prefix="${2:-}"
      shift 2
      ;;
    --dry-run)
      dry_run="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[schedule_climate_temperature] unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$delay" ]]; then
  echo "[schedule_climate_temperature] --delay is required" >&2
  exit 2
fi

if [[ -z "$entity" ]]; then
  echo "[schedule_climate_temperature] --entity is required" >&2
  exit 2
fi

if [[ -z "$temperature" ]]; then
  echo "[schedule_climate_temperature] --temperature is required" >&2
  exit 2
fi

if [[ ! -x "$SET_SCRIPT" ]]; then
  echo "[schedule_climate_temperature] set script not executable: $SET_SCRIPT" >&2
  exit 2
fi

if [[ ! "$unit_prefix" =~ ^[a-zA-Z0-9_.:-]+$ ]]; then
  echo "[schedule_climate_temperature] invalid --unit-prefix: $unit_prefix" >&2
  exit 2
fi

unit="${unit_prefix}-$(date +%Y%m%d%H%M%S)"
cmd=("$SET_SCRIPT" --entity "$entity" --temperature "$temperature" --env-file "$env_file")
if [[ "$dry_run" == "true" ]]; then
  cmd+=(--dry-run)
fi

preflight_cmd=("$SET_SCRIPT" --entity "$entity" --temperature "$temperature" --env-file "$env_file" --dry-run)
"${preflight_cmd[@]}" >/dev/null
echo "[schedule_climate_temperature] preflight=ok"

run_output="$(systemd-run --unit "$unit" --on-active="$delay" "${cmd[@]}")"
printf '%s\n' "$run_output"

echo "[schedule_climate_temperature] timer_unit=${unit}.timer"
echo "[schedule_climate_temperature] service_unit=${unit}.service"
systemctl status "${unit}.timer" --no-pager | sed -n '1,12p'
