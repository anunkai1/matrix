#!/usr/bin/env bash
set -euo pipefail

UNIT_NAME="${UNIT_NAME:-telegram-architect-bridge.service}"

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo -n "$@"
  fi
}

show_prop() {
  local key="$1"
  run_privileged systemctl show -p "${key}" --value "${UNIT_NAME}"
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

run_privileged systemctl restart "${UNIT_NAME}"

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
  run_privileged systemctl --no-pager --full status "${UNIT_NAME}"
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
  run_privileged systemctl --no-pager --full status "${UNIT_NAME}"
  exit 2
fi

echo "[restart_and_verify] verification=pass"
run_privileged systemctl --no-pager --full status "${UNIT_NAME}"
