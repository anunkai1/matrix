#!/usr/bin/env bash
set -euo pipefail

UNIT_NAME="${UNIT_NAME:-telegram-architect-bridge.service}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHAT_ROUTING_VALIDATOR="${REPO_ROOT}/ops/chat-routing/validate_chat_routing_contract.py"
ALLOWED_UNITS=(
  "telegram-architect-bridge.service"
  "telegram-agentsmith-bridge.service"
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

before_pid="$(show_prop MainPID)"
before_start="$(show_prop ExecMainStartTimestamp)"
before_mono="$(show_prop ExecMainStartTimestampMonotonic)"

echo "[restart_and_verify] request_time=$(timestamp_utc)"
echo "[restart_and_verify] before_main_pid=${before_pid}"
echo "[restart_and_verify] before_start_timestamp=${before_start}"
echo "[restart_and_verify] before_start_monotonic=${before_mono}"

systemctl restart "${UNIT_NAME}"

after_pid="$(show_prop MainPID)"
after_start="$(show_prop ExecMainStartTimestamp)"
after_mono="$(show_prop ExecMainStartTimestampMonotonic)"
active_state="$(show_prop ActiveState)"
sub_state="$(show_prop SubState)"

echo "[restart_and_verify] after_main_pid=${after_pid}"
echo "[restart_and_verify] after_start_timestamp=${after_start}"
echo "[restart_and_verify] after_start_monotonic=${after_mono}"
echo "[restart_and_verify] active_state=${active_state}"
echo "[restart_and_verify] sub_state=${sub_state}"

if [[ "${active_state}" != "active" || "${sub_state}" != "running" ]]; then
  echo "[restart_and_verify] verification=failed reason=service_not_running"
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
  systemctl --no-pager --full status "${UNIT_NAME}"
  exit 2
fi

echo "[restart_and_verify] verification=pass"
systemctl --no-pager --full status "${UNIT_NAME}"
