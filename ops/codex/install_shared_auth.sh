#!/usr/bin/env bash
set -euo pipefail

SOURCE_USER="architect"
SHARED_GROUP="codexauth"
SHARED_AUTH_PATH="/etc/server3-codex/auth.json"
REFRESH_SHARED=false
USERS=()

usage() {
  cat <<'EOF'
Usage:
  install_shared_auth.sh [options] <user> [<user> ...]

Options:
  --source-user <user>   Source user whose ~/.codex/auth.json seeds the shared file.
                         Default: architect
  --group <group>        Shared Unix group allowed to read the canonical auth file.
                         Default: codexauth
  --shared-auth <path>   Canonical shared auth file path.
                         Default: /etc/server3-codex/auth.json
  --refresh-shared       Overwrite the canonical shared auth file from the source user.
  -h, --help             Show this help.

Behavior:
  - Creates/updates one canonical auth file owned by root and readable by the shared group.
  - Ensures each target user's ~/.codex/auth.json is a symlink to the canonical auth file.
  - Keeps each target user's other ~/.codex files untouched.
EOF
}

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo -n "$@"
  fi
}

while (($#)); do
  case "$1" in
    --source-user)
      [[ $# -ge 2 ]] || { echo "--source-user requires a value" >&2; exit 2; }
      SOURCE_USER="$2"
      shift 2
      ;;
    --group)
      [[ $# -ge 2 ]] || { echo "--group requires a value" >&2; exit 2; }
      SHARED_GROUP="$2"
      shift 2
      ;;
    --shared-auth)
      [[ $# -ge 2 ]] || { echo "--shared-auth requires a value" >&2; exit 2; }
      SHARED_AUTH_PATH="$2"
      shift 2
      ;;
    --refresh-shared)
      REFRESH_SHARED=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      while (($#)); do
        USERS+=("$1")
        shift
      done
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      USERS+=("$1")
      shift
      ;;
  esac
done

if [[ ${#USERS[@]} -eq 0 ]]; then
  echo "At least one target user is required." >&2
  usage >&2
  exit 2
fi

SOURCE_AUTH_PATH="/home/${SOURCE_USER}/.codex/auth.json"
if [[ ! -s "${SOURCE_AUTH_PATH}" ]]; then
  echo "Missing source auth file: ${SOURCE_AUTH_PATH}" >&2
  exit 1
fi

SHARED_DIR="$(dirname "${SHARED_AUTH_PATH}")"

if ! getent group "${SHARED_GROUP}" >/dev/null 2>&1; then
  run_privileged groupadd --system "${SHARED_GROUP}"
fi

run_privileged install -d -m 750 -o root -g "${SHARED_GROUP}" "${SHARED_DIR}"
if [[ ! -s "${SHARED_AUTH_PATH}" || "${REFRESH_SHARED}" == "true" ]]; then
  run_privileged install -m 640 -o root -g "${SHARED_GROUP}" "${SOURCE_AUTH_PATH}" "${SHARED_AUTH_PATH}"
else
  run_privileged chown root:"${SHARED_GROUP}" "${SHARED_AUTH_PATH}"
  run_privileged chmod 640 "${SHARED_AUTH_PATH}"
fi

timestamp="$(date +%Y%m%d-%H%M%S)"
restarted_users=()

for user_name in "${USERS[@]}"; do
  passwd_entry="$(getent passwd "${user_name}" || true)"
  if [[ -z "${passwd_entry}" ]]; then
    echo "User does not exist: ${user_name}" >&2
    exit 1
  fi

  user_home="$(printf '%s\n' "${passwd_entry}" | cut -d: -f6)"
  user_group="$(id -gn "${user_name}")"
  user_codex_dir="${user_home}/.codex"
  user_auth_path="${user_codex_dir}/auth.json"

  run_privileged install -d -m 700 -o "${user_name}" -g "${user_group}" "${user_codex_dir}"

  if id -nG "${user_name}" | tr ' ' '\n' | grep -Fxq "${SHARED_GROUP}"; then
    :
  else
    run_privileged usermod -aG "${SHARED_GROUP}" "${user_name}"
    restarted_users+=("${user_name}")
  fi

  if [[ -L "${user_auth_path}" ]]; then
    current_target="$(readlink -f "${user_auth_path}" || true)"
    if [[ "${current_target}" != "${SHARED_AUTH_PATH}" ]]; then
      run_privileged mv "${user_auth_path}" "${user_auth_path}.bak.${timestamp}"
    fi
  elif [[ -e "${user_auth_path}" ]]; then
    run_privileged mv "${user_auth_path}" "${user_auth_path}.bak.${timestamp}"
  fi

  run_privileged ln -sfn "${SHARED_AUTH_PATH}" "${user_auth_path}"
  run_privileged chown -h "${user_name}:${user_group}" "${user_auth_path}"

  printf 'shared-auth linked for %s -> %s\n' "${user_name}" "${SHARED_AUTH_PATH}"
done

if [[ ${#restarted_users[@]} -gt 0 ]]; then
  printf 'group membership changed for: %s\n' "${restarted_users[*]}"
  echo "Restart those users' services or start new login sessions before relying on the shared auth."
fi
