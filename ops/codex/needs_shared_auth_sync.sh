#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MANIFEST_PATH="${REPO_ROOT}/infra/server3-runtime-manifest.json"
SOURCE_USER="${SERVER3_CODEX_AUTH_SOURCE_USER:-architect}"
SHARED_AUTH_PATH="${SERVER3_CODEX_SHARED_AUTH_PATH:-/etc/server3-codex/auth.json}"
SOURCE_AUTH_PATH="/home/${SOURCE_USER}/.codex/auth.json"

if [[ ! -s "${SOURCE_AUTH_PATH}" ]]; then
  exit 1
fi

if [[ ! -s "${SHARED_AUTH_PATH}" ]]; then
  exit 0
fi

if [[ "$(readlink -f "${SOURCE_AUTH_PATH}" 2>/dev/null || true)" != "${SHARED_AUTH_PATH}" ]]; then
  exit 0
fi

if ! cmp -s "${SOURCE_AUTH_PATH}" "${SHARED_AUTH_PATH}"; then
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

for user_name in "${target_users[@]}"; do
  passwd_entry="$(getent passwd "${user_name}" || true)"
  if [[ -z "${passwd_entry}" ]]; then
    continue
  fi
  user_home="$(printf '%s\n' "${passwd_entry}" | cut -d: -f6)"
  user_auth_path="${user_home}/.codex/auth.json"
  if [[ ! -L "${user_auth_path}" ]]; then
    exit 0
  fi
  if [[ "$(readlink -f "${user_auth_path}" 2>/dev/null || true)" != "${SHARED_AUTH_PATH}" ]]; then
    exit 0
  fi
done

exit 1
