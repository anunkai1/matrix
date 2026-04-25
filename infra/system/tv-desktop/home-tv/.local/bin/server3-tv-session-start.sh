#!/usr/bin/env bash
set -euo pipefail

if command -v xset >/dev/null 2>&1; then
  xset s off -dpms s noblank || true
fi

if command -v xfconf-query >/dev/null 2>&1; then
  xfconf-query -c xfwm4 -p /general/use_compositing -s false >/dev/null 2>&1 || true
fi

"${HOME}/.local/bin/server3-tv-display.sh" &
"${HOME}/.local/bin/server3-tv-audio.sh" &
exit 0
