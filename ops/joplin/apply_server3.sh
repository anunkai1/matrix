#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'HELP'
Usage:
  apply_server3.sh --url <https://nextcloud.example.com> --username <user> --app-password <password> [--webdav-path </remote.php/dav/files/<user>/Joplin>] [--direction pull|push]

Installs Joplin CLI for the current user (if missing) and configures Nextcloud WebDAV sync.
Defaults:
- webdav-path: /remote.php/dav/files/<username>/Joplin
- direction: pull
HELP
}

URL=""
USERNAME=""
APP_PASSWORD=""
WEBDAV_PATH=""
DIRECTION="pull"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url)
      URL="${2:-}"
      shift 2
      ;;
    --username)
      USERNAME="${2:-}"
      shift 2
      ;;
    --app-password)
      APP_PASSWORD="${2:-}"
      shift 2
      ;;
    --webdav-path)
      WEBDAV_PATH="${2:-}"
      shift 2
      ;;
    --direction)
      DIRECTION="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[joplin-apply] unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$URL" || -z "$USERNAME" || -z "$APP_PASSWORD" ]]; then
  echo "[joplin-apply] --url, --username and --app-password are required" >&2
  usage >&2
  exit 2
fi

if [[ "$DIRECTION" != "pull" && "$DIRECTION" != "push" ]]; then
  echo "[joplin-apply] invalid --direction: $DIRECTION (expected pull|push)" >&2
  exit 2
fi

if [[ -z "$WEBDAV_PATH" ]]; then
  WEBDAV_PATH="/remote.php/dav/files/${USERNAME}/Joplin"
fi
if [[ "${WEBDAV_PATH:0:1}" != "/" ]]; then
  WEBDAV_PATH="/${WEBDAV_PATH}"
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "[joplin-apply] npm is required but not found in PATH" >&2
  exit 2
fi

export NPM_CONFIG_PREFIX="${HOME}/.local"
export PATH="${NPM_CONFIG_PREFIX}/bin:${PATH}"

if ! command -v joplin >/dev/null 2>&1; then
  mkdir -p "${NPM_CONFIG_PREFIX}"
  npm install -g joplin
fi

BASE_URL="${URL%/}"
SYNC_URL="${BASE_URL}${WEBDAV_PATH}"

joplin config sync.target 5
joplin config sync.5.path "${SYNC_URL}"
joplin config sync.5.username "${USERNAME}"
joplin config sync.5.password "${APP_PASSWORD}"

# Ensure the remote Joplin folder exists to avoid initial MKCOL 409 on locks/.
if command -v curl >/dev/null 2>&1; then
  HTTP_CODE="$(curl -sS -o /tmp/joplin-mkcol.$$ -w '%{http_code}' \
    -u "${USERNAME}:${APP_PASSWORD}" \
    -X MKCOL "${SYNC_URL}" || true)"
  rm -f /tmp/joplin-mkcol.$$
  if [[ "$HTTP_CODE" != "201" && "$HTTP_CODE" != "405" ]]; then
    echo "[joplin-apply] warning: MKCOL ${SYNC_URL} returned HTTP ${HTTP_CODE}" >&2
  fi
fi

if [[ "$DIRECTION" == "pull" ]]; then
  # Fresh Server3 bootstrap: pull remote notes into local profile.
  joplin sync --use-lock 0
else
  joplin sync --use-lock 0
fi

echo "[joplin-apply] joplin version: $(joplin version)"
echo "[joplin-apply] sync.target: $(joplin config sync.target)"
echo "[joplin-apply] sync.5.path: $(joplin config sync.5.path)"
