#!/usr/bin/env bash
set -euo pipefail

NEXTCLOUD_OPS_ENV_FILE_DEFAULT="/home/architect/.config/nextcloud/ops.env"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Required command not found: $cmd" >&2
    exit 3
  fi
}

load_nextcloud_ops_env() {
  local env_file="${NEXTCLOUD_OPS_ENV_FILE:-$NEXTCLOUD_OPS_ENV_FILE_DEFAULT}"
  if [[ ! -f "$env_file" ]]; then
    echo "Nextcloud ops env file not found: $env_file" >&2
    exit 4
  fi

  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a

  : "${NEXTCLOUD_BASE_URL:?NEXTCLOUD_BASE_URL missing in env file}"
  : "${NEXTCLOUD_USERNAME:?NEXTCLOUD_USERNAME missing in env file}"
  : "${NEXTCLOUD_APP_PASSWORD:?NEXTCLOUD_APP_PASSWORD missing in env file}"

  NEXTCLOUD_BASE_URL="${NEXTCLOUD_BASE_URL%/}"
}

normalize_remote_path() {
  local input="${1:-/}"
  if [[ -z "$input" ]]; then
    input="/"
  fi
  if [[ "$input" != /* ]]; then
    input="/$input"
  fi
  printf '%s' "$input"
}

nextcloud_auth_curl() {
  curl -k -sS -u "${NEXTCLOUD_USERNAME}:${NEXTCLOUD_APP_PASSWORD}" "$@"
}
