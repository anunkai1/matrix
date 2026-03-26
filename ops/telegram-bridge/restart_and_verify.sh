#!/usr/bin/env bash
set -euo pipefail

UNIT_NAME="${UNIT_NAME:-telegram-architect-bridge.service}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHAT_ROUTING_VALIDATOR="${REPO_ROOT}/ops/chat-routing/validate_chat_routing_contract.py"
RESTART_WAIT_FOR_IDLE="${RESTART_WAIT_FOR_IDLE:-true}"
RESTART_IDLE_TIMEOUT_SECONDS="${RESTART_IDLE_TIMEOUT_SECONDS:-120}"
RESTART_IDLE_POLL_SECONDS="${RESTART_IDLE_POLL_SECONDS:-2}"
RESTART_STATUS_DIR="${RESTART_STATUS_DIR:-/tmp}"
ALLOWED_UNITS=(
  "telegram-architect-bridge.service"
  "telegram-agentsmith-bridge.service"
  "telegram-diary-bridge.service"
  "telegram-tank-bridge.service"
  "telegram-trinity-bridge.service"
  "telegram-mavali-eth-bridge.service"
  "telegram-macrorayd-bridge.service"
  "govorun-whatsapp-bridge.service"
  "oracle-signal-bridge.service"
)

is_allowed_unit() {
  local candidate="$1"
  for allowed in "${ALLOWED_UNITS[@]}"; do
    if [[ "${candidate}" == "${allowed}" ]]; then
      return 0
    fi
  done
  return 1
}

is_truthy() {
  local value="${1:-}"
  case "${value,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

resolve_environment_file() {
  systemctl cat "${UNIT_NAME}" 2>/dev/null | sed -n 's/^EnvironmentFile=-\{0,1\}//p' | head -n 1
}

load_unit_environment() {
  local env_file
  local line key value
  env_file="$(resolve_environment_file)"
  if [[ -z "${env_file}" || ! -f "${env_file}" ]]; then
    return 0
  fi

  while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    if [[ -z "${line}" || "${line}" == \#* ]]; then
      continue
    fi
    if [[ "${line}" != *=* ]]; then
      continue
    fi
    key="${line%%=*}"
    value="${line#*=}"
    if [[ ! "${key}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      continue
    fi
    printf -v "${key}" '%s' "${value}"
    export "${key}"
  done < "${env_file}"
}

count_in_flight_requests() {
  python3 - "$@" <<'PY'
import json
import sqlite3
import sys
from pathlib import Path

state_dir = sys.argv[1]
canonical_sqlite_enabled = sys.argv[2].strip().lower() in {"1", "true", "yes", "on"}
canonical_sqlite_path = Path(sys.argv[3])
canonical_json_path = Path(sys.argv[4])
in_flight_json_path = Path(sys.argv[5])

def count_canonical_json(path: Path):
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return sum(
        1
        for value in payload.values()
        if isinstance(value, dict) and value.get("in_flight_started_at") is not None
    )

def count_legacy_json(path: Path):
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return len(payload)

if canonical_sqlite_enabled and canonical_sqlite_path.exists():
    try:
        with sqlite3.connect(str(canonical_sqlite_path)) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM canonical_sessions WHERE in_flight_started_at IS NOT NULL"
            ).fetchone()
        print(int(row[0] or 0))
        raise SystemExit(0)
    except Exception:
        pass

canonical_json_count = count_canonical_json(canonical_json_path)
if canonical_json_count is not None:
    print(canonical_json_count)
    raise SystemExit(0)

legacy_count = count_legacy_json(in_flight_json_path)
if legacy_count is not None:
    print(legacy_count)
    raise SystemExit(0)

print(0)
PY
}

wait_for_idle_if_needed() {
  local state_dir canonical_sqlite_enabled canonical_sqlite_path canonical_json_path in_flight_json_path
  local deadline now in_flight_count

  if ! is_truthy "${RESTART_WAIT_FOR_IDLE}"; then
    echo "[restart_and_verify] idle_wait=disabled"
    return 0
  fi

  load_unit_environment
  state_dir="${TELEGRAM_BRIDGE_STATE_DIR:-/home/architect/.local/state/telegram-architect-bridge}"
  canonical_sqlite_enabled="${TELEGRAM_CANONICAL_SQLITE_ENABLED:-false}"
  canonical_sqlite_path="${TELEGRAM_CANONICAL_SQLITE_PATH:-${state_dir}/chat_sessions.sqlite3}"
  canonical_json_path="${state_dir}/chat_sessions.json"
  in_flight_json_path="${state_dir}/in_flight_requests.json"
  deadline=$(( $(date +%s) + RESTART_IDLE_TIMEOUT_SECONDS ))

  while true; do
    in_flight_count="$(
      count_in_flight_requests \
        "${state_dir}" \
        "${canonical_sqlite_enabled}" \
        "${canonical_sqlite_path}" \
        "${canonical_json_path}" \
        "${in_flight_json_path}"
    )"
    if [[ "${in_flight_count}" == "0" ]]; then
      echo "[restart_and_verify] idle_wait=clear state_dir=${state_dir}"
      return 0
    fi

    now="$(date +%s)"
    if (( now >= deadline )); then
      echo "[restart_and_verify] idle_wait=timeout in_flight_count=${in_flight_count} state_dir=${state_dir}" >&2
      return 1
    fi

    echo "[restart_and_verify] idle_wait=waiting in_flight_count=${in_flight_count} state_dir=${state_dir}"
    sleep "${RESTART_IDLE_POLL_SECONDS}"
  done
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --unit)
      UNIT_NAME="${2:-}"
      shift 2
      ;;
    *)
      echo "Usage: $0 [--unit UNIT_NAME]" >&2
      exit 1
      ;;
  esac
done

if [[ -z "${UNIT_NAME}" ]]; then
  echo "UNIT_NAME cannot be empty" >&2
  exit 1
fi

if ! is_allowed_unit "${UNIT_NAME}"; then
  echo "[restart_and_verify] UNIT_NAME is not allowed: ${UNIT_NAME}" >&2
  echo "[restart_and_verify] allowed units: ${ALLOWED_UNITS[*]}" >&2
  exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
  exec sudo -n "$0" --unit "${UNIT_NAME}"
fi

if [[ "${UNIT_NAME}" == "govorun-whatsapp-bridge.service" ]]; then
  if [[ ! -f "${CHAT_ROUTING_VALIDATOR}" ]]; then
    echo "[restart_and_verify] contract validator not found: ${CHAT_ROUTING_VALIDATOR}" >&2
    exit 1
  fi
  echo "[restart_and_verify] running chat-routing contract check"
  /usr/bin/python3 "${CHAT_ROUTING_VALIDATOR}"
fi

show_prop() {
  local key="$1"
  systemctl show -p "${key}" --value "${UNIT_NAME}"
}

timestamp_utc() {
  date -u +"%Y-%m-%d %H:%M:%S UTC"
}

status_path_for_unit() {
  local sanitized
  sanitized="$(printf '%s' "${UNIT_NAME}" | tr -c 'A-Za-z0-9._-' '_')"
  printf '%s/restart_and_verify.%s.status.json' "${RESTART_STATUS_DIR}" "${sanitized}"
}

write_status() {
  local phase="$1"
  local verification="$2"
  local reason="${3:-}"
  python3 - "${STATUS_PATH}" "${phase}" "${verification}" "${reason}" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
phase = sys.argv[2]
verification = sys.argv[3]
reason = sys.argv[4]

payload = {
    "unit_name": os.environ.get("UNIT_NAME", ""),
    "phase": phase,
    "verification": verification,
    "reason": reason,
    "request_time": os.environ.get("REQUEST_TIME_UTC", ""),
    "before_main_pid": os.environ.get("before_pid", ""),
    "before_start_timestamp": os.environ.get("before_start", ""),
    "after_main_pid": os.environ.get("after_pid", ""),
    "after_start_timestamp": os.environ.get("after_start", ""),
    "active_state": os.environ.get("active_state", ""),
    "sub_state": os.environ.get("sub_state", ""),
}
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

before_pid="$(show_prop MainPID)"
before_start="$(show_prop ExecMainStartTimestamp)"
before_mono="$(show_prop ExecMainStartTimestampMonotonic)"
REQUEST_TIME_UTC="$(timestamp_utc)"
STATUS_PATH="$(status_path_for_unit)"
export REQUEST_TIME_UTC STATUS_PATH before_pid before_start

echo "[restart_and_verify] request_time=${REQUEST_TIME_UTC}"
echo "[restart_and_verify] before_main_pid=${before_pid}"
echo "[restart_and_verify] before_start_timestamp=${before_start}"
echo "[restart_and_verify] before_start_monotonic=${before_mono}"
echo "[restart_and_verify] status_path=${STATUS_PATH}"

write_status "requested" "pending"

if ! wait_for_idle_if_needed; then
  write_status "failed" "failed" "idle_timeout"
  exit 1
fi

systemctl restart "${UNIT_NAME}"

after_pid="$(show_prop MainPID)"
after_start="$(show_prop ExecMainStartTimestamp)"
after_mono="$(show_prop ExecMainStartTimestampMonotonic)"
active_state="$(show_prop ActiveState)"
sub_state="$(show_prop SubState)"
export after_pid after_start active_state sub_state

echo "[restart_and_verify] after_main_pid=${after_pid}"
echo "[restart_and_verify] after_start_timestamp=${after_start}"
echo "[restart_and_verify] after_start_monotonic=${after_mono}"
echo "[restart_and_verify] active_state=${active_state}"
echo "[restart_and_verify] sub_state=${sub_state}"

if [[ "${active_state}" != "active" || "${sub_state}" != "running" ]]; then
  echo "[restart_and_verify] verification=failed reason=service_not_running"
  write_status "failed" "failed" "service_not_running"
  systemctl --no-pager --full status "${UNIT_NAME}"
  exit 1
fi

changed_marker="no"
if [[ "${before_mono}" != "${after_mono}" ]]; then
  changed_marker="yes"
elif [[ "${before_pid}" != "${after_pid}" ]]; then
  changed_marker="yes"
fi

if [[ "${changed_marker}" != "yes" ]]; then
  echo "[restart_and_verify] verification=failed reason=no_restart_marker_change"
  write_status "failed" "failed" "no_restart_marker_change"
  systemctl --no-pager --full status "${UNIT_NAME}"
  exit 2
fi

echo "[restart_and_verify] verification=pass"
write_status "completed" "pass"
systemctl --no-pager --full status "${UNIT_NAME}"
