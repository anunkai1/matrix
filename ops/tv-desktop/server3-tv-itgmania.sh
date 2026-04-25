#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  server3-tv-itgmania.sh [--restart] [--no-fullscreen]

Starts the Server3 TV desktop if needed and launches ITGmania as the tv user.

Options:
  --restart       Stop an existing tv-user ITGmania process before launching.
  --no-fullscreen Do not force the ITGmania window into fullscreen via wmctrl.
USAGE
}

RESTART_EXISTING=0
FORCE_FULLSCREEN=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --restart)
      RESTART_EXISTING=1
      ;;
    --no-fullscreen)
      FORCE_FULLSCREEN=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

TV_HOME="/home/tv"
ITGMANIA_BIN="${SERVER3_TV_ITGMANIA_BIN:-/opt/itgmania/itgmania}"
LOG_PATH="${SERVER3_TV_ITGMANIA_LOG:-/tmp/server3-tv-itgmania.log}"

if [[ ! -x "${ITGMANIA_BIN}" ]]; then
  echo "ITGmania binary not found or not executable: ${ITGMANIA_BIN}" >&2
  exit 3
fi

if ! systemctl is-active --quiet lightdm.service; then
  /usr/local/bin/server3-tv-start
  sleep 2
fi

if ! id tv >/dev/null 2>&1; then
  echo "tv user not found." >&2
  exit 4
fi

TV_UID="$(id -u tv)"
DISPLAY_VALUE="${SERVER3_TV_DISPLAY:-:0}"
XAUTHORITY_VALUE="${TV_HOME}/.Xauthority"
RUNTIME_DIR="/run/user/${TV_UID}"
BUS_PATH="/run/user/${TV_UID}/bus"
PULSE_SOCKET="${RUNTIME_DIR}/pulse/native"

wait_for_tv_session() {
  local attempts=30
  local delay=1
  local attempt
  for attempt in $(seq 1 "${attempts}"); do
    if pgrep -u tv -x xfce4-session >/dev/null 2>&1 \
      && sudo -u tv test -f "${XAUTHORITY_VALUE}" \
      && sudo -u tv test -d "${RUNTIME_DIR}"; then
      return 0
    fi
    sleep "${delay}"
  done

  echo "TV desktop session did not become ready." >&2
  return 1
}

build_env_vars() {
  ENV_VARS=(
    "HOME=${TV_HOME}"
    "USER=tv"
    "LOGNAME=tv"
    "DISPLAY=${DISPLAY_VALUE}"
    "XAUTHORITY=${XAUTHORITY_VALUE}"
    "XDG_RUNTIME_DIR=${RUNTIME_DIR}"
  )

  if sudo -u tv test -S "${BUS_PATH}" 2>/dev/null; then
    ENV_VARS+=("DBUS_SESSION_BUS_ADDRESS=unix:path=${BUS_PATH}")
  fi

  if sudo -u tv test -S "${PULSE_SOCKET}" 2>/dev/null; then
    ENV_VARS+=("PULSE_SERVER=unix:${PULSE_SOCKET}")
  fi
}

wait_for_tv_audio() {
  local attempts=20
  local delay=1
  local attempt

  if [[ -x "${TV_HOME}/.local/bin/server3-tv-audio.sh" ]]; then
    sudo -u tv env "${ENV_VARS[@]}" "${TV_HOME}/.local/bin/server3-tv-audio.sh" >/dev/null 2>&1 || true
  fi

  if ! command -v pactl >/dev/null 2>&1; then
    return 0
  fi

  for attempt in $(seq 1 "${attempts}"); do
    if sudo -u tv test -S "${PULSE_SOCKET}" 2>/dev/null \
      && sudo -u tv env "${ENV_VARS[@]}" pactl get-default-sink >/dev/null 2>&1; then
      return 0
    fi
    sleep "${delay}"
  done

  echo "TV audio service did not become ready; launching ITGmania with its fallback audio path." >&2
  return 0
}

stop_existing_itgmania() {
  local attempts=10
  local delay=1
  local attempt

  sudo pkill -TERM -u tv -x itgmania >/dev/null 2>&1 || true
  for attempt in $(seq 1 "${attempts}"); do
    if ! pgrep -u tv -x itgmania >/dev/null 2>&1; then
      return 0
    fi
    sleep "${delay}"
  done

  sudo pkill -KILL -u tv -x itgmania >/dev/null 2>&1 || true
}

focus_itgmania_window() {
  if ! command -v wmctrl >/dev/null 2>&1; then
    return 0
  fi

  local attempts=30
  local delay=1
  local attempt
  local window_id
  for attempt in $(seq 1 "${attempts}"); do
    window_id="$(
      sudo -u tv env "${ENV_VARS[@]}" wmctrl -lx 2>/dev/null \
        | awk 'tolower($0) ~ /itgmania/ {print $1}' \
        | tail -n 1
    )"
    if [[ -n "${window_id}" ]]; then
      sudo -u tv env "${ENV_VARS[@]}" wmctrl -i -a "${window_id}" >/dev/null 2>&1 || true
      if (( FORCE_FULLSCREEN == 1 )); then
        sudo -u tv env "${ENV_VARS[@]}" wmctrl -i -r "${window_id}" -b add,fullscreen >/dev/null 2>&1 || true
      fi
      echo "${window_id}"
      return 0
    fi
    sleep "${delay}"
  done

  echo "Timed out waiting for ITGmania window." >&2
  return 1
}

wait_for_tv_session
build_env_vars
wait_for_tv_audio
build_env_vars

if (( RESTART_EXISTING == 1 )); then
  stop_existing_itgmania
fi

existing_pid="$(pgrep -u tv -x itgmania | head -n 1 || true)"
if [[ -n "${existing_pid}" ]]; then
  window_id="$(focus_itgmania_window || true)"
  echo "[server3-tv-itgmania] already_running=1 pid=${existing_pid} window=${window_id:-unknown} fullscreen=${FORCE_FULLSCREEN}"
  exit 0
fi

sudo install -d -m 755 -o tv -g tv "${TV_HOME}/.local/state"
sudo -u tv env "${ENV_VARS[@]}" nohup "${ITGMANIA_BIN}" >"${LOG_PATH}" 2>&1 < /dev/null &

sleep 1
pid="$(pgrep -u tv -x itgmania | head -n 1 || true)"
if [[ -z "${pid}" ]]; then
  echo "ITGmania exited before creating a process. Log: ${LOG_PATH}" >&2
  tail -n 80 "${LOG_PATH}" >&2 || true
  exit 5
fi

window_id="$(focus_itgmania_window || true)"
echo "[server3-tv-itgmania] launched=1 pid=${pid} window=${window_id:-unknown} fullscreen=${FORCE_FULLSCREEN} log=${LOG_PATH}"
