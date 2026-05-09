#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
session_name="${SERVER3_REVIEW_FIX_LOOP_TMUX_SESSION:-server3-review-fix-loop}"
state_dir="${SERVER3_REVIEW_FIX_LOOP_FALLBACK_STATE_DIR:-${repo_root}/.state/server3-review-fix-loop}"
log_path="${state_dir}/tmux.log"

usage() {
  cat <<'EOF'
Usage: tmux_control.sh <start|status|logs|attach|stop>

Start and manage the temporary review-fix loop in a detached tmux session.
EOF
}

loop_script="${repo_root}/ops/review_fix_loop/review_fix_loop.py"

tmux_session_exists() {
  tmux has-session -t "${session_name}" 2>/dev/null
}

start_session() {
  mkdir -p "${state_dir}"
  if tmux_session_exists; then
    echo "already_running session=${session_name}"
    return 0
  fi
  local launch_cmd
  launch_cmd="$(printf "cd %q && python3 %q run 2>&1 | tee -a %q" "${repo_root}" "${loop_script}" "${log_path}")"
  tmux new-session -d -s "${session_name}" "${launch_cmd}"
  echo "started session=${session_name} log=${log_path}"
}

show_status() {
  if tmux_session_exists; then
    echo "session=${session_name} running=yes"
  else
    echo "session=${session_name} running=no"
  fi
  python3 "${loop_script}" status
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

main() {
  local command="${1:-}"
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
}

main "$@"
