#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'HELP'
Usage:
  rollback_server3.sh [--remove-packages] [--remove-user]

Rolls back Server3 TV desktop rollout:
- stop/disable LightDM
- remove tv desktop live config/scripts
- restore previous default target if recorded

Optional:
- --remove-packages: remove desktop/browser packages installed by apply
- --remove-user: remove `tv` user and home directory
HELP
}

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

REMOVE_PACKAGES="no"
REMOVE_USER="no"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remove-packages)
      REMOVE_PACKAGES="yes"
      shift
      ;;
    --remove-user)
      REMOVE_USER="yes"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[rollback_server3] unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

STATE_DIR="/var/lib/server3-tv-desktop"

run_privileged systemctl stop lightdm >/dev/null 2>&1 || true
run_privileged systemctl disable lightdm >/dev/null 2>&1 || true

run_privileged rm -f /etc/lightdm/lightdm.conf.d/50-server3-tv-autologin.conf
run_privileged rm -f /usr/local/bin/server3-tv-start /usr/local/bin/server3-tv-stop

if id -u tv >/dev/null 2>&1; then
  run_privileged rm -f /home/tv/.config/autostart/server3-tv-brave.desktop
  run_privileged rm -f /home/tv/.local/bin/server3-tv-session-start.sh
  run_privileged rm -f /home/tv/.local/bin/server3-tv-audio.sh
fi

if [[ -f "${STATE_DIR}/default-target.before" ]]; then
  previous_target="$(<"${STATE_DIR}/default-target.before")"
  if [[ -n "${previous_target}" ]]; then
    run_privileged systemctl set-default "${previous_target}" || true
  fi
fi

if [[ "${REMOVE_USER}" == "yes" ]] && id -u tv >/dev/null 2>&1; then
  run_privileged userdel -r tv || true
fi

if [[ "${REMOVE_PACKAGES}" == "yes" ]]; then
  run_privileged apt-get remove -y \
    brave-browser \
    xfce4 \
    xfce4-terminal \
    lightdm \
    lightdm-gtk-greeter \
    xorg \
    dbus-x11 \
    pipewire-audio \
    wireplumber \
    pulseaudio-utils || true
  run_privileged rm -f /etc/apt/sources.list.d/brave-browser-release.list
  run_privileged rm -f /usr/share/keyrings/brave-browser-archive-keyring.gpg
  run_privileged apt-get update || true
fi

echo "[rollback_server3] complete"
echo "[rollback_server3] default target: $(systemctl get-default)"
echo "[rollback_server3] lightdm enabled: $(systemctl is-enabled lightdm 2>/dev/null || true)"
