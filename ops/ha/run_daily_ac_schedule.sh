#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SET_MODE_SCRIPT="$SCRIPT_DIR/set_climate_mode.sh"
SET_TEMP_SCRIPT="$SCRIPT_DIR/set_climate_temperature.sh"
POWER_SCRIPT="$SCRIPT_DIR/turn_entity_power.sh"
DEFAULT_ENV_FILE="${HA_OPS_ENV_FILE:-/etc/default/ha-ops}"

MID_ROOM_ENTITY="climate.mid_kids_rm_aircon"
LIVING_ROOM_ENTITY="climate.living_rm_aircon"

usage() {
  cat <<'EOF'
Usage:
  run_daily_ac_schedule.sh --slot SLOT [options]

Options:
  --slot SLOT       One of: midnight-heat, morning-heat, morning-off
  --env-file PATH   Home Assistant env file
                    (default: /etc/default/ha-ops)
  --dry-run         Validate and print planned actions without writing to HA
  -h, --help        Show this help text
EOF
}

slot=""
env_file="$DEFAULT_ENV_FILE"
dry_run="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --slot)
      slot="${2:-}"
      shift 2
      ;;
    --env-file)
      env_file="${2:-}"
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
      echo "[run_daily_ac_schedule] unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$slot" ]]; then
  echo "[run_daily_ac_schedule] --slot is required" >&2
  exit 2
fi

run_set_mode() {
  local entity="$1"
  local mode="$2"
  local cmd=("$SET_MODE_SCRIPT" --entity "$entity" --mode "$mode" --env-file "$env_file")
  if [[ "$dry_run" == "true" ]]; then
    cmd+=(--dry-run)
  fi
  "${cmd[@]}"
}

run_set_temp() {
  local entity="$1"
  local temperature="$2"
  local cmd=("$SET_TEMP_SCRIPT" --entity "$entity" --temperature "$temperature" --env-file "$env_file")
  if [[ "$dry_run" == "true" ]]; then
    cmd+=(--dry-run)
  fi
  "${cmd[@]}"
}

run_power() {
  local action="$1"
  local entity="$2"
  local cmd=("$POWER_SCRIPT" --action "$action" --entity "$entity" --env-file "$env_file")
  if [[ "$dry_run" == "true" ]]; then
    cmd+=(--dry-run)
  fi
  "${cmd[@]}"
}

apply_heat() {
  local entity="$1"
  local temperature="$2"
  run_set_mode "$entity" "heat"
  run_set_temp "$entity" "$temperature"
}

case "$slot" in
  midnight-heat)
    echo "[run_daily_ac_schedule] slot=midnight-heat target=$MID_ROOM_ENTITY mode=heat temperature=22"
    apply_heat "$MID_ROOM_ENTITY" "22"
    ;;
  morning-heat)
    echo "[run_daily_ac_schedule] slot=morning-heat targets=$MID_ROOM_ENTITY,$LIVING_ROOM_ENTITY mode=heat temperature=26"
    apply_heat "$MID_ROOM_ENTITY" "26"
    apply_heat "$LIVING_ROOM_ENTITY" "26"
    ;;
  morning-off)
    echo "[run_daily_ac_schedule] slot=morning-off targets=$MID_ROOM_ENTITY,$LIVING_ROOM_ENTITY action=off"
    run_power "off" "$MID_ROOM_ENTITY"
    run_power "off" "$LIVING_ROOM_ENTITY"
    ;;
  *)
    echo "[run_daily_ac_schedule] unsupported --slot value: $slot" >&2
    exit 2
    ;;
esac
