#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'HELP'
Usage:
  turn_entity_power.sh --action on|off --entity domain.entity_id [options]

Options:
  --env-file PATH   Environment file containing TELEGRAM_HA_BASE_URL/TELEGRAM_HA_TOKEN
                    (default: /etc/default/ha-ops)
  --base-url URL    Home Assistant base URL (overrides env-file value)
  --dry-run         Validate inputs and print target action without calling Home Assistant
  -h, --help        Show this help text
HELP
}

trim_wrapped_quotes() {
  local value="$1"
  value="${value#\"}"
  value="${value%\"}"
  value="${value#\'}"
  value="${value%\'}"
  printf '%s' "$value"
}

extract_env_value() {
  local file_path="$1"
  local key="$2"
  local line
  line="$(grep -E "^${key}=" "$file_path" | tail -n 1 || true)"
  if [[ -z "$line" ]]; then
    return 1
  fi
  trim_wrapped_quotes "${line#*=}"
}

preflight_ha_api() {
  local resolved_base_url="$1"
  local resolved_token="$2"
  if ! curl -fsS -m 5 -H "Authorization: Bearer $resolved_token" \
    "${resolved_base_url}/api/" >/dev/null; then
    echo "[turn_entity_power] Home Assistant API preflight failed: ${resolved_base_url}/api/" >&2
    exit 2
  fi
}

action=""
entity=""
env_file="${HA_OPS_ENV_FILE:-/etc/default/ha-ops}"
base_url="${HA_BASE_URL:-}"
token="${TELEGRAM_HA_TOKEN:-${HA_TOKEN:-}}"
dry_run="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --action)
      action="${2:-}"
      shift 2
      ;;
    --entity)
      entity="${2:-}"
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
      echo "[turn_entity_power] --token is not allowed. Use --env-file or HA_OPS_ENV_FILE." >&2
      exit 2
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
      echo "[turn_entity_power] unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$action" ]]; then
  echo "[turn_entity_power] --action is required (on|off)" >&2
  exit 2
fi

if [[ "$action" != "on" && "$action" != "off" ]]; then
  echo "[turn_entity_power] --action must be 'on' or 'off': $action" >&2
  exit 2
fi

if [[ -z "$entity" ]]; then
  echo "[turn_entity_power] --entity is required" >&2
  exit 2
fi

if [[ ! "$entity" =~ ^[a-z0-9_]+\.[a-z0-9_]+$ ]]; then
  echo "[turn_entity_power] invalid entity format: $entity" >&2
  exit 2
fi

if [[ -z "$base_url" || -z "$token" ]]; then
  if [[ ! -r "$env_file" ]]; then
    echo "[turn_entity_power] env file is not readable: $env_file" >&2
    exit 2
  fi
fi

if [[ -z "$base_url" ]]; then
  base_url="$(extract_env_value "$env_file" "TELEGRAM_HA_BASE_URL" || true)"
fi
if [[ -z "$base_url" ]]; then
  base_url="$(extract_env_value "$env_file" "HA_BASE_URL" || true)"
fi
if [[ -z "$token" ]]; then
  token="$(extract_env_value "$env_file" "TELEGRAM_HA_TOKEN" || true)"
fi
if [[ -z "$token" ]]; then
  token="$(extract_env_value "$env_file" "HA_TOKEN" || true)"
fi

if [[ -z "$base_url" ]]; then
  echo "[turn_entity_power] missing Home Assistant base URL" >&2
  exit 2
fi

if [[ -z "$token" ]]; then
  echo "[turn_entity_power] missing Home Assistant token" >&2
  exit 2
fi

base_url="${base_url%/}"
service="turn_${action}"
payload="$(printf '{"entity_id":"%s"}' "$entity")"
preflight_ha_api "$base_url" "$token"

if [[ "$dry_run" == "true" ]]; then
  echo "[turn_entity_power] dry_run=true action=$action entity=$entity env_file=$env_file base_url=$base_url service=homeassistant/$service preflight=ok"
  exit 0
fi

curl -fsS -X POST \
  -H "Authorization: Bearer $token" \
  -H "Content-Type: application/json" \
  "$base_url/api/services/homeassistant/$service" \
  -d "$payload" >/dev/null

state_json="$(curl -fsS -H "Authorization: Bearer $token" "$base_url/api/states/$entity")"
state_value="$(printf '%s' "$state_json" | jq -r '.state // empty' 2>/dev/null || true)"

if [[ -n "$state_value" ]]; then
  echo "[turn_entity_power] success action=$action entity=$entity state=$state_value"
else
  echo "[turn_entity_power] $service call succeeded for entity=$entity"
fi
