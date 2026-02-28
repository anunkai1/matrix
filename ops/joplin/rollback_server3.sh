#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'HELP'
Usage:
  rollback_server3.sh [--purge-profile]

Rollback actions:
- remove user-level Joplin CLI (npm global under ~/.local)
- optionally remove local Joplin profile (~/.config/joplin)
HELP
}

PURGE_PROFILE="no"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --purge-profile)
      PURGE_PROFILE="yes"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[joplin-rollback] unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

export NPM_CONFIG_PREFIX="${HOME}/.local"
export PATH="${NPM_CONFIG_PREFIX}/bin:${PATH}"

if command -v npm >/dev/null 2>&1; then
  npm uninstall -g joplin >/dev/null 2>&1 || true
fi

if [[ -f "${HOME}/.local/bin/joplin" ]]; then
  rm -f "${HOME}/.local/bin/joplin"
fi

if [[ "$PURGE_PROFILE" == "yes" ]]; then
  rm -rf "${HOME}/.config/joplin"
fi

echo "[joplin-rollback] rollback complete"
