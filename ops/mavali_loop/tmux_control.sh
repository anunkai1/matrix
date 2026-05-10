#!/usr/bin/env bash
set -euo pipefail

standalone_script="/home/architect/mavali-loop/scripts/tmux_control.sh"
if [[ ! -x "${standalone_script}" ]]; then
  echo "standalone mavali-loop tmux controller is missing: ${standalone_script}" >&2
  exit 1
fi

exec "${standalone_script}" "$@"
