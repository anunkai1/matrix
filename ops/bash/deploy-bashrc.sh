#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-apply}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SNIPPET="${REPO_ROOT}/infra/bash/home/architect/.bashrc"
TARGET="${TARGET_BASHRC:-/home/architect/.bashrc}"
START="# >>> matrix-managed architect launcher >>>"
END="# <<< matrix-managed architect launcher <<<"

if [[ ! -f "${SNIPPET}" ]]; then
  echo "Snippet not found: ${SNIPPET}" >&2
  exit 1
fi

if [[ ! -f "${TARGET}" ]]; then
  touch "${TARGET}"
fi

backup="${TARGET}.bak.$(date +%Y%m%d%H%M%S).$$"
cp "${TARGET}" "${backup}"
echo "Backup created: ${backup}"

tmp="$(mktemp)"
awk -v s="${START}" -v e="${END}" '
$0 == s { in_block = 1; next }
$0 == e { in_block = 0; next }
!in_block { print }
' "${TARGET}" > "${tmp}"

case "${MODE}" in
  apply)
    {
      cat "${tmp}"
      printf "\n%s\n" "${START}"
      cat "${SNIPPET}"
      printf "%s\n" "${END}"
    } > "${TARGET}"
    echo "Applied architect launcher to ${TARGET}"
    ;;
  rollback)
    cat "${tmp}" > "${TARGET}"
    echo "Removed managed architect launcher block from ${TARGET}"
    ;;
  *)
    echo "Usage: $0 [apply|rollback]" >&2
    echo "Optional override: TARGET_BASHRC=/custom/path/.bashrc" >&2
    rm -f "${tmp}"
    exit 1
    ;;
esac

rm -f "${tmp}"
