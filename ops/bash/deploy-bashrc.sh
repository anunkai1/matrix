#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-apply}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASHRC_PROFILE="${BASHRC_PROFILE:-architect}"
SNIPPET="${SNIPPET_PATH:-${REPO_ROOT}/infra/bash/home/${BASHRC_PROFILE}/.bashrc}"
TARGET="${TARGET_BASHRC:-/home/${BASHRC_PROFILE}/.bashrc}"
START="# >>> matrix-managed ${BASHRC_PROFILE} launcher >>>"
END="# <<< matrix-managed ${BASHRC_PROFILE} launcher <<<"

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
    echo "Applied ${BASHRC_PROFILE} launcher to ${TARGET}"
    ;;
  rollback)
    cat "${tmp}" > "${TARGET}"
    echo "Removed managed ${BASHRC_PROFILE} launcher block from ${TARGET}"
    ;;
  *)
    echo "Usage: $0 [apply|rollback]" >&2
    echo "Optional overrides: BASHRC_PROFILE=<profile> TARGET_BASHRC=/custom/path/.bashrc SNIPPET_PATH=/custom/snippet" >&2
    rm -f "${tmp}"
    exit 1
    ;;
esac

rm -f "${tmp}"
