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
  # Optional override for operators, e.g. "-s danger-full-access --color never"
  read -r -a EXEC_ARGS <<<"${ARCHITECT_EXEC_ARGS}"
else
  EXEC_ARGS=(-s danger-full-access --color never)
fi

out_file="$(mktemp)"
log_file="$(mktemp)"
cleanup() {
  rm -f "${out_file}" "${log_file}"
}
trap cleanup EXIT

if ! printf '%s\n' "${prompt}" | "${CODEX_BIN}" exec "${EXEC_ARGS[@]}" --output-last-message "${out_file}" - >"${log_file}" 2>&1; then
  tail -n 80 "${log_file}" >&2 || true
  exit 1
fi

if [[ ! -s "${out_file}" ]]; then
  echo "No output returned by codex exec" >&2
  tail -n 80 "${log_file}" >&2 || true
  exit 1
fi

cat "${out_file}"
