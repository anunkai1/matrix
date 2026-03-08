#!/usr/bin/env bash
set -euo pipefail

PROFILE="${JOPLIN_PROFILE:-/home/architect/.config/joplin}"

export HOME="${HOME:-/home/architect}"
export PATH="/home/architect/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

if ! command -v joplin >/dev/null 2>&1; then
  echo "[joplin-sync] joplin binary not found in PATH" >&2
  exit 127
fi

exec joplin --profile "${PROFILE}" sync --use-lock 0
