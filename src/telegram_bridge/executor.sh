#!/usr/bin/env bash
set -euo pipefail

mode="${1:-new}"
if [[ "${mode}" != "new" && "${mode}" != "resume" ]]; then
  echo "Usage: $0 [new|resume] [thread_id] [--image FILE]..." >&2
  exit 2
fi
if (($# > 0)); then
  shift
fi

if [[ "${mode}" == "resume" ]]; then
  thread_id="${1:-}"
  if [[ -z "${thread_id}" ]]; then
    echo "thread_id is required in resume mode" >&2
    exit 2
  fi
  shift
else
  thread_id=""
fi

IMAGE_ARGS=()
while (($#)); do
  case "$1" in
    --image)
      if (($# < 2)); then
        echo "--image requires a file path" >&2
        exit 2
      fi
      image_path="$2"
      if [[ ! -f "${image_path}" ]]; then
        echo "image file not found: ${image_path}" >&2
        exit 2
      fi
      IMAGE_ARGS+=(-i "${image_path}")
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [new|resume] [thread_id] [--image FILE]..." >&2
      exit 2
      ;;
  esac
done

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
  # Optional override for operators, applied to new sessions only.
  read -r -a EXEC_ARGS <<<"${ARCHITECT_EXEC_ARGS}"
else
  EXEC_ARGS=(--color never)
fi

if [[ "${mode}" == "resume" ]]; then
  CMD=("${CODEX_BIN}" exec resume --dangerously-bypass-approvals-and-sandbox --json "${IMAGE_ARGS[@]}" "${thread_id}" -)
else
  CMD=("${CODEX_BIN}" exec --dangerously-bypass-approvals-and-sandbox "${EXEC_ARGS[@]}" --json "${IMAGE_ARGS[@]}" -)
fi

printf '%s\n' "${prompt}" | "${CMD[@]}"
