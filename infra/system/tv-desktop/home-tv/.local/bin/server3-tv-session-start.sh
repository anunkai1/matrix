#!/usr/bin/env bash
set -euo pipefail

if command -v xset >/dev/null 2>&1; then
  xset s off -dpms s noblank || true
fi

"${HOME}/.local/bin/server3-tv-audio.sh" &

BROWSER_BIN="$(command -v brave-browser || true)"
if [[ -z "${BROWSER_BIN}" ]]; then
  exit 0
fi

exec "${BROWSER_BIN}" \
  --no-default-browser-check \
  --no-first-run \
  --start-maximized \
  --new-window "https://www.youtube.com"
