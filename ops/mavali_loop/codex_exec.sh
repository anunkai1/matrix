#!/usr/bin/env bash
set -euo pipefail

standalone_script="/home/architect/mavali-loop/scripts/codex_exec.sh"
if [[ ! -x "${standalone_script}" ]]; then
  echo "standalone mavali-loop executor is missing: ${standalone_script}" >&2
  exit 1
fi

exec "${standalone_script}" "$@"
