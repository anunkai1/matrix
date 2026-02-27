#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'HELP'
Usage:
  apply_server3.sh

Applies the Server3 TV desktop target state:
- keeps default boot in CLI mode (`multi-user.target`)
- installs Xfce + LightDM + Brave
- creates local-only `tv` desktop user (locked password, no sudo)
- configures LightDM autologin for `tv`
- installs start/stop commands:
  - /usr/local/bin/server3-tv-start
  - /usr/local/bin/server3-tv-stop
- configures tv session autostart for Brave fullscreen + HDMI audio preference
HELP
}

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -gt 0 ]]; then
  echo "[apply_server3] unknown arguments: $*" >&2
  usage >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TEMPLATE_ROOT="${REPO_ROOT}/infra/system/tv-desktop"
STATE_DIR="/var/lib/server3-tv-desktop"

for template in \
  "${TEMPLATE_ROOT}/lightdm/50-server3-tv-autologin.conf" \
  "${TEMPLATE_ROOT}/usr-local-bin/server3-tv-start" \
  "${TEMPLATE_ROOT}/usr-local-bin/server3-tv-stop" \
  "${TEMPLATE_ROOT}/home-tv/.local/bin/server3-tv-audio.sh" \
  "${TEMPLATE_ROOT}/home-tv/.local/bin/server3-tv-session-start.sh" \
  "${TEMPLATE_ROOT}/home-tv/.config/autostart/server3-tv-brave.desktop"; do
  if [[ ! -f "${template}" ]]; then
    echo "[apply_server3] template missing: ${template}" >&2
    exit 2
  fi
done

run_privileged install -d -m 755 "${STATE_DIR}"
if [[ ! -f "${STATE_DIR}/default-target.before" ]]; then
  current_target="$(systemctl get-default)"
  printf '%s\n' "${current_target}" | run_privileged tee "${STATE_DIR}/default-target.before" >/dev/null
fi

export DEBIAN_FRONTEND=noninteractive
run_privileged apt-get update
run_privileged apt-get install -y --no-install-recommends ca-certificates curl gnupg

echo 'lightdm shared/default-x-display-manager select lightdm' | run_privileged debconf-set-selections
echo 'lightdm lightdm/default-display-manager select lightdm' | run_privileged debconf-set-selections

run_privileged install -d -m 755 /usr/share/keyrings
if [[ ! -f /usr/share/keyrings/brave-browser-archive-keyring.gpg ]]; then
  curl -fsSL https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg \
    | run_privileged tee /usr/share/keyrings/brave-browser-archive-keyring.gpg >/dev/null
fi

cat <<'BRAVEAPT' | run_privileged tee /etc/apt/sources.list.d/brave-browser-release.list >/dev/null
deb [signed-by=/usr/share/keyrings/brave-browser-archive-keyring.gpg] https://brave-browser-apt-release.s3.brave.com/ stable main
BRAVEAPT

run_privileged apt-get update
run_privileged apt-get install -y \
  xorg \
  lightdm \
  lightdm-gtk-greeter \
  xfce4 \
  xfce4-terminal \
  dbus-x11 \
  pipewire-audio \
  wireplumber \
  pulseaudio-utils \
  brave-browser

if ! id -u tv >/dev/null 2>&1; then
  run_privileged useradd -m -s /bin/bash tv
fi

run_privileged passwd -l tv >/dev/null 2>&1 || true
run_privileged usermod -aG audio,video tv
if id -nG tv | tr ' ' '\n' | grep -qx 'sudo'; then
  run_privileged gpasswd -d tv sudo >/dev/null || true
fi

run_privileged install -d -m 755 /etc/lightdm/lightdm.conf.d
run_privileged install -m 644 \
  "${TEMPLATE_ROOT}/lightdm/50-server3-tv-autologin.conf" \
  /etc/lightdm/lightdm.conf.d/50-server3-tv-autologin.conf

run_privileged install -m 755 \
  "${TEMPLATE_ROOT}/usr-local-bin/server3-tv-start" \
  /usr/local/bin/server3-tv-start
run_privileged install -m 755 \
  "${TEMPLATE_ROOT}/usr-local-bin/server3-tv-stop" \
  /usr/local/bin/server3-tv-stop

run_privileged install -d -m 755 /home/tv/.local/bin
run_privileged install -d -m 755 /home/tv/.config/autostart

run_privileged install -m 755 \
  "${TEMPLATE_ROOT}/home-tv/.local/bin/server3-tv-audio.sh" \
  /home/tv/.local/bin/server3-tv-audio.sh
run_privileged install -m 755 \
  "${TEMPLATE_ROOT}/home-tv/.local/bin/server3-tv-session-start.sh" \
  /home/tv/.local/bin/server3-tv-session-start.sh
run_privileged install -m 644 \
  "${TEMPLATE_ROOT}/home-tv/.config/autostart/server3-tv-brave.desktop" \
  /home/tv/.config/autostart/server3-tv-brave.desktop

run_privileged chown -R tv:tv /home/tv/.local /home/tv/.config

run_privileged systemctl set-default multi-user.target
run_privileged systemctl disable lightdm >/dev/null 2>&1 || true
run_privileged systemctl stop lightdm >/dev/null 2>&1 || true

echo "[apply_server3] complete"
echo "[apply_server3] default target: $(systemctl get-default)"
echo "[apply_server3] lightdm enabled: $(systemctl is-enabled lightdm 2>/dev/null || true)"
echo "[apply_server3] tv start cmd: /usr/local/bin/server3-tv-start"
echo "[apply_server3] tv stop cmd: /usr/local/bin/server3-tv-stop"
