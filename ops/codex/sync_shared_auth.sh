#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MANIFEST_PATH="${REPO_ROOT}/infra/server3-runtime-manifest.json"
INSTALL_SCRIPT="${REPO_ROOT}/ops/codex/install_shared_auth.sh"
SOURCE_USER="${SERVER3_CODEX_AUTH_SOURCE_USER:-architect}"
SHARED_AUTH_PATH="${SERVER3_CODEX_SHARED_AUTH_PATH:-/etc/server3-codex/auth.json}"

if [[ ! -x "${INSTALL_SCRIPT}" ]]; then
  exit 0
fi

if [[ ! -s "/home/${SOURCE_USER}/.codex/auth.json" ]]; then
  exit 0
fi

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
    return
  fi
  if sudo -n true >/dev/null 2>&1; then
    sudo -n "$@"
    return
  fi
  return 1
}

if ! run_privileged test -d "$(dirname "${SHARED_AUTH_PATH}")" >/dev/null 2>&1; then
  exit 0
fi

mapfile -t target_users < <(
  python3 - "${MANIFEST_PATH}" "${SOURCE_USER}" <<'PY'
import json
import pathlib
import sys

manifest_path = pathlib.Path(sys.argv[1])
source_user = sys.argv[2].strip()
users = []
seen = set()

def add(user: str) -> None:
    value = user.strip()
    if not value or value in seen:
        return
    seen.add(value)
    users.append(value)

add(source_user)
if manifest_path.exists():
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in payload.get("runtimes", []):
        dependencies = entry.get("dependencies") or []
        has_codex = any("authenticated Codex executor" in str(item) for item in dependencies)
        if has_codex:
            add(str(entry.get("owner_user") or ""))

for user in users:
    print(user)
PY
)

if [[ ${#target_users[@]} -eq 0 ]]; then
  target_users=("${SOURCE_USER}")
fi

source_auth_path="/home/${SOURCE_USER}/.codex/auth.json"
refresh_flag=()
if [[ "$(readlink -f "${source_auth_path}" 2>/dev/null || true)" != "${SHARED_AUTH_PATH}" ]]; then
  refresh_flag=(--refresh-shared)
fi

"${INSTALL_SCRIPT}" --source-user "${SOURCE_USER}" --shared-auth "${SHARED_AUTH_PATH}" "${refresh_flag[@]}" "${target_users[@]}"
