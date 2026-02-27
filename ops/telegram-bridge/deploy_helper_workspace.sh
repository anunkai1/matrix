#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-apply}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET_ROOT="${TARGET_ROOT:-/home/helperbot/helperbot}"
TARGET_OWNER="${TARGET_OWNER:-helperbot}"
TARGET_GROUP="${TARGET_GROUP:-helperbot}"
REPO_URL="${REPO_URL:-https://github.com/anunkai1/matrix.git}"

install_identity_files() {
  sudo install -o "${TARGET_OWNER}" -g "${TARGET_GROUP}" -m 0644 \
    "${REPO_ROOT}/infra/helperbot/AGENTS.md" \
    "${TARGET_ROOT}/AGENTS.md"
  sudo install -o "${TARGET_OWNER}" -g "${TARGET_GROUP}" -m 0644 \
    "${REPO_ROOT}/infra/helperbot/HELPER_INSTRUCTION.md" \
    "${TARGET_ROOT}/HELPER_INSTRUCTION.md"
}

case "${MODE}" in
  apply)
    if [[ ! -d "${TARGET_ROOT}/.git" ]]; then
      sudo -u "${TARGET_OWNER}" git clone "${REPO_URL}" "${TARGET_ROOT}"
    else
      sudo -u "${TARGET_OWNER}" git -C "${TARGET_ROOT}" fetch --prune origin
      sudo -u "${TARGET_OWNER}" git -C "${TARGET_ROOT}" checkout -f main
      sudo -u "${TARGET_OWNER}" git -C "${TARGET_ROOT}" reset --hard origin/main
    fi
    install_identity_files
    echo "Helper workspace deployed at ${TARGET_ROOT}"
    ;;
  status)
    if [[ ! -d "${TARGET_ROOT}" ]]; then
      echo "missing: ${TARGET_ROOT}"
      exit 1
    fi
    ls -ld "${TARGET_ROOT}"
    sudo -u "${TARGET_OWNER}" git -C "${TARGET_ROOT}" rev-parse --short HEAD
    sudo -u "${TARGET_OWNER}" git -C "${TARGET_ROOT}" status --short
    ;;
  *)
    echo "Usage: $0 [apply|status]" >&2
    exit 1
    ;;
esac
