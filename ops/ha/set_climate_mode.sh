#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'HELP'
Usage:
  set_climate_mode.sh --entity climate.entity_id --mode MODE [options]

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
    echo "[set_climate_mode] Home Assistant API preflight failed: ${resolved_base_url}/api/" >&2
    exit 2
  fi
}

entity=""
mode=""
env_file="${HA_OPS_ENV_FILE:-/etc/default/ha-ops}"
base_url="${HA_BASE_URL:-}"
token="${TELEGRAM_HA_TOKEN:-${HA_TOKEN:-}}"
dry_run="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
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
      echo "[set_climate_mode] --token is not allowed. Use --env-file or HA_OPS_ENV_FILE." >&2
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
      echo "[set_climate_mode] unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$entity" ]]; then
  echo "[set_climate_mode] --entity is required" >&2
  exit 2
fi

if [[ -z "$mode" ]]; then
  echo "[set_climate_mode] --mode is required" >&2
  exit 2
fi

if [[ ! "$entity" =~ ^[a-z0-9_]+\.[a-z0-9_]+$ ]]; then
  echo "[set_climate_mode] invalid entity format: $entity" >&2
  exit 2
fi

if [[ "$entity" != climate.* ]]; then
  echo "[set_climate_mode] entity must be a climate entity: $entity" >&2
  exit 2
fi

if [[ ! "$mode" =~ ^[a-z_]+$ ]]; then
  echo "[set_climate_mode] invalid mode format: $mode" >&2
  exit 2
fi

if [[ -z "$base_url" || -z "$token" ]]; then
  if [[ ! -r "$env_file" ]]; then
    echo "[set_climate_mode] env file is not readable: $env_file" >&2
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
  echo "[set_climate_mode] missing Home Assistant base URL" >&2
  exit 2
fi

if [[ -z "$token" ]]; then
  echo "[set_climate_mode] missing Home Assistant token" >&2
  exit 2
fi

base_url="${base_url%/}"
preflight_ha_api "$base_url" "$token"

# Validate requested mode against entity capabilities before attempting write.
state_json="$(curl -fsS -H "Authorization: Bearer $token" "$base_url/api/states/$entity")"
if ! printf '%s' "$state_json" | jq -e --arg m "$mode" '.attributes.hvac_modes // [] | index($m) != null' >/dev/null; then
  modes="$(printf '%s' "$state_json" | jq -r '.attributes.hvac_modes // [] | join(",")' 2>/dev/null || true)"
  echo "[set_climate_mode] mode '$mode' not supported by $entity (supported: ${modes:-unknown})" >&2
  exit 2
fi

if [[ "$dry_run" == "true" ]]; then
  echo "[set_climate_mode] dry_run=true entity=$entity mode=$mode env_file=$env_file base_url=$base_url preflight=ok"
  exit 0
fi

payload="$(printf '{"entity_id":"%s","hvac_mode":"%s"}' "$entity" "$mode")"
curl -fsS -X POST \
  -H "Authorization: Bearer $token" \
  -H "Content-Type: application/json" \
  "$base_url/api/services/climate/set_hvac_mode" \
  -d "$payload" >/dev/null

post_state_json="$(curl -fsS -H "Authorization: Bearer $token" "$base_url/api/states/$entity")"
state_mode="$(printf '%s' "$post_state_json" | jq -r '.state // empty' 2>/dev/null || true)"

if [[ -n "$state_mode" ]]; then
  echo "[set_climate_mode] success entity=$entity mode=$mode state=$state_mode"
else
  echo "[set_climate_mode] set_hvac_mode call succeeded for entity=$entity mode=$mode"
fi
