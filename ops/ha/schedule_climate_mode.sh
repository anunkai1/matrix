#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SET_SCRIPT="$SCRIPT_DIR/set_climate_mode.sh"

usage() {
  cat <<'HELP'
Usage:
  schedule_climate_mode.sh (--in DURATION | --at WHEN) --entity climate.entity_id --mode MODE [options]

Options:
  --in DURATION      Relative delay (examples: "5 minutes", "2h", "in 30 seconds")
  --at WHEN          Absolute time (examples: "07:00", "2026-02-23 19:00", "tomorrow 7am")
  --entity ID        Home Assistant climate entity id (domain.object_id)
  --mode MODE        HVAC mode (for example: dry, cool, heat, fan_only)
  --env-file PATH    Env file consumed by set_climate_mode.sh
                     (default: /etc/default/ha-ops)
  --base-url URL     Home Assistant base URL (overrides env-file value)
  --token TOKEN      Home Assistant token (overrides env-file value)
  --unit-prefix NAME Prefix for transient systemd unit names
                     (default: ha-climate-mode)
  --dry-run          Schedule a dry-run execution (no Home Assistant write)
  -h, --help         Show this help text
HELP
}

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo -n "$@"
  fi
}

trim_value() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

normalize_in_spec() {
  local spec
  spec="$(trim_value "$1")"
  if [[ "$spec" =~ ^[iI][nN][[:space:]]+(.+)$ ]]; then
    spec="${BASH_REMATCH[1]}"
  fi
  trim_value "$spec"
}

resolve_at_spec() {
  local spec="$1"
  local now_epoch
  local target_epoch
  local candidate_input

  spec="$(trim_value "$spec")"
  if [[ -z "$spec" ]]; then
    echo "[schedule_climate_mode] --at cannot be empty" >&2
    return 2
  fi

  now_epoch="$(date +%s)"

  if [[ "$spec" =~ ^([01]?[0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9])?$ ]]; then
    candidate_input="$(date +%F) $spec"
    target_epoch="$(date -d "$candidate_input" +%s 2>/dev/null || true)"
    if [[ -z "$target_epoch" ]]; then
      echo "[schedule_climate_mode] invalid --at time: $spec" >&2
      return 2
    fi
    if (( target_epoch <= now_epoch )); then
      target_epoch="$(date -d "$candidate_input +1 day" +%s 2>/dev/null || true)"
      if [[ -z "$target_epoch" ]]; then
        echo "[schedule_climate_mode] could not resolve next day for --at: $spec" >&2
        return 2
      fi
    fi
  else
    target_epoch="$(date -d "$spec" +%s 2>/dev/null || true)"
    if [[ -z "$target_epoch" ]]; then
      echo "[schedule_climate_mode] invalid --at value: $spec" >&2
      return 2
    fi
    if (( target_epoch <= now_epoch )); then
      echo "[schedule_climate_mode] --at must resolve to a future time: $spec" >&2
      return 2
    fi
  fi

  date -d "@$target_epoch" '+%Y-%m-%d %H:%M:%S'
}

in_spec=""
at_spec=""
entity=""
mode=""
env_file="/etc/default/ha-ops"
base_url=""
token=""
unit_prefix="ha-climate-mode"
dry_run="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --in)
      in_spec="${2:-}"
      shift 2
      ;;
    --at)
      at_spec="${2:-}"
      shift 2
      ;;
    --entity)
      entity="${2:-}"
      shift 2
      ;;
    --mode)
      mode="${2:-}"
      shift 2
      ;;
    --env-file)
      env_file="${2:-}"
      shift 2
      ;;
    --base-url)
      base_url="${2:-}"
      shift 2
      ;;
    --token)
      token="${2:-}"
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
      echo "[schedule_climate_mode] unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$in_spec" && -z "$at_spec" ]]; then
  echo "[schedule_climate_mode] one of --in or --at is required" >&2
  exit 2
fi

if [[ -n "$in_spec" && -n "$at_spec" ]]; then
  echo "[schedule_climate_mode] use either --in or --at, not both" >&2
  exit 2
fi

if [[ -z "$entity" ]]; then
  echo "[schedule_climate_mode] --entity is required" >&2
  exit 2
fi

if [[ -z "$mode" ]]; then
  echo "[schedule_climate_mode] --mode is required" >&2
  exit 2
fi

if [[ ! "$unit_prefix" =~ ^[a-zA-Z0-9_.:-]+$ ]]; then
  echo "[schedule_climate_mode] invalid --unit-prefix: $unit_prefix" >&2
  exit 2
fi

if [[ ! -x "$SET_SCRIPT" ]]; then
  echo "[schedule_climate_mode] set script not executable: $SET_SCRIPT" >&2
  exit 2
fi

unit="${unit_prefix}-$(date +%Y%m%d%H%M%S)"
cmd=("$SET_SCRIPT" --entity "$entity" --mode "$mode" --env-file "$env_file")
if [[ -n "$base_url" ]]; then
  cmd+=(--base-url "$base_url")
fi
if [[ -n "$token" ]]; then
  cmd+=(--token "$token")
fi
if [[ "$dry_run" == "true" ]]; then
  cmd+=(--dry-run)
fi

preflight_cmd=("$SET_SCRIPT" --entity "$entity" --mode "$mode" --env-file "$env_file" --dry-run)
if [[ -n "$base_url" ]]; then
  preflight_cmd+=(--base-url "$base_url")
fi
if [[ -n "$token" ]]; then
  preflight_cmd+=(--token "$token")
fi
run_privileged "${preflight_cmd[@]}" >/dev/null
echo "[schedule_climate_mode] preflight=ok"

if [[ -n "$in_spec" ]]; then
  in_spec="$(normalize_in_spec "$in_spec")"
  if [[ -z "$in_spec" ]]; then
    echo "[schedule_climate_mode] --in resolved to empty duration" >&2
    exit 2
  fi
  run_output="$(run_privileged systemd-run --unit "$unit" --on-active="$in_spec" "${cmd[@]}")"
  trigger_desc="in=$in_spec"
else
  on_calendar="$(resolve_at_spec "$at_spec")"
  run_output="$(run_privileged systemd-run --unit "$unit" --on-calendar="$on_calendar" "${cmd[@]}")"
  trigger_desc="at=$on_calendar"
fi

printf '%s\n' "$run_output"

echo "[schedule_climate_mode] trigger=$trigger_desc"
echo "[schedule_climate_mode] timer_unit=${unit}.timer"
echo "[schedule_climate_mode] service_unit=${unit}.service"
run_privileged systemctl status "${unit}.timer" --no-pager | sed -n '1,12p'
