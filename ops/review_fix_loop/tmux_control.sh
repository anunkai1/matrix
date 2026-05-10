#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
standalone_root="/home/architect/mavali-loop"
campaign_path="${standalone_root}/campaigns/examples/server3_code_review_may_2026.json"
delegate_script="${standalone_root}/scripts/tmux_control.sh"

export SERVER3_MAVALI_LOOP_TMUX_SESSION="${SERVER3_REVIEW_FIX_LOOP_TMUX_SESSION:-server3-review-fix-loop}"

if [[ $# -eq 0 ]]; then
  exec bash "${delegate_script}" start "${campaign_path}"
fi

exec bash "${delegate_script}" "${1:-}" "${campaign_path}"
