#!/usr/bin/env bash
set -euo pipefail

if ! command -v pactl >/dev/null 2>&1; then
  exit 0
fi

for _ in $(seq 1 30); do
  sink="$(pactl list short sinks 2>/dev/null | awk 'BEGIN{IGNORECASE=1} /hdmi|alsa_output.*hdmi/ {print $1; exit}')"
  if [[ -n "${sink}" ]]; then
    pactl set-default-sink "${sink}" || true
    pactl list short sink-inputs 2>/dev/null | awk '{print $1}' | while read -r input_id; do
      pactl move-sink-input "${input_id}" "${sink}" || true
    done
    exit 0
  fi
  sleep 1
done

exit 0
