#!/usr/bin/env bash
set -euo pipefail

prompt="$(cat)"
if [[ -z "${prompt}" ]]; then
  echo "Prompt is empty" >&2
  exit 2
fi

CODEX_BIN="${CODEX_BIN:-codex}"
if ! command -v "${CODEX_BIN}" >/dev/null 2>&1; then
  echo "codex binary not found: ${CODEX_BIN}" >&2
  exit 127
fi

if [[ -n "${ARCHITECT_EXEC_ARGS:-}" ]]; then
  # Optional override for operators, e.g. "-s danger-full-access -a never"
  read -r -a EXEC_ARGS <<<"${ARCHITECT_EXEC_ARGS}"
else
  EXEC_ARGS=(-s danger-full-access -a never)
fi

exec "${CODEX_BIN}" "${EXEC_ARGS[@]}" "${prompt}"
