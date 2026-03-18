#!/usr/bin/env bash
set -euo pipefail

TARGET_ROOT="/"
desired_codex_version="${SERVER3_CODEX_VERSION:-0.114.0}"

usage() {
  cat <<'EOF'
Usage: bootstrap_host.sh [--target /]

Installs baseline host prerequisites and recreates Server3 service users on a
fresh Ubuntu host after the state archive has been restored.
EOF
}

while (($# > 0)); do
  case "$1" in
    --target)
      TARGET_ROOT="${2:?missing target root}"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

if [[ "${TARGET_ROOT}" != "/" ]]; then
  echo "bootstrap_host.sh currently supports only --target /" >&2
  exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "bootstrap_host.sh must run as root." >&2
  exit 1
fi

ensure_group() {
  local name="$1"
  local gid="$2"

  if getent group "${name}" >/dev/null; then
    return
  fi

  if getent group "${gid}" >/dev/null; then
    echo "Group GID ${gid} already exists with another name; cannot create ${name}." >&2
    exit 1
  fi

  groupadd --gid "${gid}" "${name}"
}

ensure_user() {
  local name="$1"
  local uid="$2"
  local gid="$3"
  local home_dir="$4"
  local shell="$5"

  if id -u "${name}" >/dev/null 2>&1; then
    return
  fi

  if getent passwd "${uid}" >/dev/null; then
    echo "UID ${uid} already exists with another user; cannot create ${name}." >&2
    exit 1
  fi

  ensure_group "${name}" "${gid}"
  useradd --uid "${uid}" --gid "${gid}" --create-home --home-dir "${home_dir}" --shell "${shell}" "${name}"
}

install_if_available() {
  local package_name="$1"
  if apt-cache show "${package_name}" >/dev/null 2>&1; then
    apt-get install -y "${package_name}"
  else
    echo "Package not available from current apt sources: ${package_name}" >&2
  fi
}

apt-get update
apt-get install -y ca-certificates curl docker.io git jq npm python3 python3-pip python3-venv sqlite3
install_if_available docker-compose-v2
install_if_available tailscale
install_if_available tailscale-archive-keyring
install_if_available nordvpn

if ! getent passwd 1000 >/dev/null; then
  ensure_user "anunakii" "1000" "1000" "/home/anunakii" "/bin/bash"
fi

ensure_user "architect" "1001" "1001" "/home/architect" "/bin/bash"
ensure_user "tank" "1002" "1002" "/home/tank" "/bin/bash"
ensure_user "tv" "1003" "1003" "/home/tv" "/bin/bash"
ensure_user "govorun" "1005" "1005" "/home/govorun" "/bin/bash"
ensure_user "oracle" "1007" "1007" "/home/oracle" "/bin/bash"
ensure_user "macrorayd" "1008" "1008" "/home/macrorayd" "/bin/bash"
ensure_user "trinity" "1009" "1009" "/home/trinity" "/bin/bash"
ensure_user "browser_brain" "1010" "1010" "/home/browser_brain" "/bin/bash"
ensure_user "agentsmith" "1011" "1011" "/home/agentsmith" "/bin/bash"

mkdir -p /srv/external/server3-arr
mkdir -p /srv/external/server3-backups
mkdir -p /srv/media-stack
mkdir -p /srv/server3-monitoring
mkdir -p /var/lib/node_exporter_textfile

systemctl enable docker
systemctl start docker

if command -v codex >/dev/null 2>&1; then
  current_codex_version="$(codex --version 2>/dev/null | awk '{print $2}')"
else
  current_codex_version=""
fi
if [[ "${current_codex_version}" != "${desired_codex_version}" ]]; then
  npm install -g "@openai/codex@${desired_codex_version}"
fi

echo "Host bootstrap completed."
