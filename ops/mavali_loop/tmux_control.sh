#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
campaign_path="${2:-}"

usage() {
  cat <<'EOF'
Usage: tmux_control.sh <start|status|logs|attach|stop> <campaign-spec.json>

Start and manage a Mavali Loop campaign in a detached tmux session.
EOF
}

if [[ $# -lt 2 ]]; then
  usage >&2
  exit 1
fi

if [[ ! -f "${campaign_path}" ]]; then
  echo "campaign_missing path=${campaign_path}" >&2
  exit 1
fi

campaign_id="$(python3 - <<'PY' "${campaign_path}"
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload["campaign_id"])
PY
)"

slug="$(printf '%s' "${campaign_id}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g')"
session_name="${SERVER3_MAVALI_LOOP_TMUX_SESSION:-${SERVER3_MAVALI_LOOP_TMUX_SESSION_PREFIX:-server3-mavali-loop}-${slug}}"
state_root="${SERVER3_MAVALI_LOOP_FALLBACK_STATE_DIR:-${repo_root}/.state/server3-mavali-loop}"
campaign_state_dir="${state_root}/${slug}"
log_path="${campaign_state_dir}/tmux.log"
loop_script="${repo_root}/ops/mavali_loop/mavali_loop.py"

tmux_session_exists() {
  tmux has-session -t "${session_name}" 2>/dev/null
}

start_session() {
  mkdir -p "${campaign_state_dir}"
  if tmux_session_exists; then
    echo "already_running session=${session_name}"
    return 0
  fi
  local launch_cmd
  launch_cmd="$(printf "cd %q && python3 %q run %q 2>&1 | tee -a %q" "${repo_root}" "${loop_script}" "${campaign_path}" "${log_path}")"
  tmux new-session -d -s "${session_name}" "${launch_cmd}"
  echo "started session=${session_name} log=${log_path}"
}

show_status() {
  if tmux_session_exists; then
    echo "session=${session_name} running=yes"
  else
    echo "session=${session_name} running=no"
  fi
  python3 "${loop_script}" status "${campaign_path}"
}

show_logs() {
  if [[ ! -f "${log_path}" ]]; then
    echo "log_missing path=${log_path}"
    return 0
  fi
  tail -n 100 "${log_path}"
}

attach_session() {
  exec tmux attach-session -t "${session_name}"
}

stop_session() {
  if ! tmux_session_exists; then
    echo "already_stopped session=${session_name}"
    return 0
  fi
  tmux kill-session -t "${session_name}"
  echo "stopped session=${session_name}"
}

command="${1:-}"
case "${command}" in
  start)
    start_session
    ;;
  status)
    show_status
    ;;
  logs)
    show_logs
    ;;
  attach)
    attach_session
    ;;
  stop)
    stop_session
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac
