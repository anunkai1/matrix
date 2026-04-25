#!/usr/bin/env bash
set -euo pipefail

DISPLAY_MODE="${SERVER3_TV_MODE:-1280x720}"
DISPLAY_RATE="${SERVER3_TV_RATE:-}"

if ! command -v xrandr >/dev/null 2>&1; then
  exit 0
fi

hdmi_output=""
for _ in $(seq 1 20); do
  hdmi_output="$(
    xrandr --query 2>/dev/null \
      | awk '$2 == "connected" && $1 ~ /^HDMI/ {print $1; exit}'
  )"
  if [[ -n "${hdmi_output}" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "${hdmi_output}" ]]; then
  exit 0
fi

xrandr_args=(--output "${hdmi_output}" --primary --mode "${DISPLAY_MODE}" --pos 0x0)
if [[ -n "${DISPLAY_RATE}" ]]; then
  xrandr_args+=(--rate "${DISPLAY_RATE}")
fi

xrandr "${xrandr_args[@]}" >/dev/null 2>&1 \
  || xrandr --output "${hdmi_output}" --primary --auto --pos 0x0 >/dev/null 2>&1 \
  || true

xrandr --query 2>/dev/null \
  | awk -v keep="${hdmi_output}" '$2 == "connected" && $1 != keep {print $1}' \
  | while read -r output; do
    xrandr --output "${output}" --off >/dev/null 2>&1 || true
  done

if command -v wmctrl >/dev/null 2>&1; then
  wmctrl -lx 2>/dev/null \
    | awk 'tolower($0) ~ /xfce4-display-settings/ {print $1}' \
    | while read -r window_id; do
      wmctrl -ic "${window_id}" >/dev/null 2>&1 || true
    done
fi
