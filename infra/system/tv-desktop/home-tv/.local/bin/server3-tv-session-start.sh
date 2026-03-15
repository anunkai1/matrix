#!/usr/bin/env bash
set -euo pipefail

if command -v xset >/dev/null 2>&1; then
  xset s off -dpms s noblank || true
fi

"${HOME}/.local/bin/server3-tv-audio.sh" &
exit 0
