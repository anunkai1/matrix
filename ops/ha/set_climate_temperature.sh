#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  set_climate_temperature.sh --entity climate.entity_id --temperature 25 [options]

Options:
  --env-file PATH   Environment file containing TELEGRAM_HA_BASE_URL/TELEGRAM_HA_TOKEN
                    (default: /etc/default/telegram-architect-bridge)
  --base-url URL    Home Assistant base URL (overrides env-file value)
  --token TOKEN     Home Assistant token (overrides env-file value)
  --dry-run         Validate inputs and print target action without calling Home Assistant
  -h, --help        Show this help text
EOF
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

entity=""
temperature=""
env_file="/etc/default/telegram-architect-bridge"
base_url="${HA_BASE_URL:-}"
token="${HA_TOKEN:-}"
dry_run="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
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
    --base-url)
      base_url="${2:-}"
      shift 2
      ;;
    --token)
      token="${2:-}"
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
      echo "[set_climate_temperature] unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$entity" ]]; then
  echo "[set_climate_temperature] --entity is required" >&2
  exit 2
fi

if [[ -z "$temperature" ]]; then
  echo "[set_climate_temperature] --temperature is required" >&2
  exit 2
fi

if [[ ! "$entity" =~ ^[a-z0-9_]+\.[a-z0-9_]+$ ]]; then
  echo "[set_climate_temperature] invalid entity format: $entity" >&2
  exit 2
fi

if [[ "$entity" != climate.* ]]; then
  echo "[set_climate_temperature] entity must be a climate entity: $entity" >&2
  exit 2
fi

if [[ ! "$temperature" =~ ^-?[0-9]+([.][0-9]+)?$ ]]; then
  echo "[set_climate_temperature] invalid temperature: $temperature" >&2
  exit 2
fi

if [[ -z "$base_url" || -z "$token" ]]; then
  if [[ ! -r "$env_file" ]]; then
    echo "[set_climate_temperature] env file is not readable: $env_file" >&2
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
  echo "[set_climate_temperature] missing Home Assistant base URL" >&2
  exit 2
fi

if [[ -z "$token" ]]; then
  echo "[set_climate_temperature] missing Home Assistant token" >&2
  exit 2
fi

base_url="${base_url%/}"
payload="$(printf '{"entity_id":"%s","temperature":%s}' "$entity" "$temperature")"

if [[ "$dry_run" == "true" ]]; then
  echo "[set_climate_temperature] dry_run=true entity=$entity temperature=$temperature env_file=$env_file base_url=$base_url"
  exit 0
fi

curl -fsS -X POST \
  -H "Authorization: Bearer $token" \
  -H "Content-Type: application/json" \
  "$base_url/api/services/climate/set_temperature" \
  -d "$payload" >/dev/null

state_json="$(curl -fsS -H "Authorization: Bearer $token" "$base_url/api/states/$entity")"
state_temp="$(printf '%s' "$state_json" | jq -r '.attributes.temperature // empty' 2>/dev/null || true)"
state_mode="$(printf '%s' "$state_json" | jq -r '.state // empty' 2>/dev/null || true)"

if [[ -n "$state_temp" ]]; then
  echo "[set_climate_temperature] success entity=$entity temperature=$state_temp state=$state_mode"
else
  echo "[set_climate_temperature] set_temperature call succeeded for entity=$entity"
fi
